"""대상 기업 목록(universe) 만들기.

1) 최근 12개월 정기공시(사업/반기/분기보고서) 제출 기업을 모은다.
2) 각 기업의 최신 정기보고서에서
   회사채 / 기업어음(CP) / 단기사채(전단채) 미상환 잔액을 조회한다.
3) 상장사(유가·코스닥·코넥스) 또는 미상환 잔액 > 0 인 기업을 대상으로 한다.

결과: data/universe.json
  - 이미 확인한 보고서(rcept_no)는 다시 조회하지 않는다 (호출 수 절약).
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import dart

WORKERS = int(os.environ.get("DART_WORKERS", "10"))
BUDGET_MIN = float(os.environ.get("UNIVERSE_BUDGET_MIN", "120"))

BAL_APIS = {
    "bond": "cprndNrdmpBlce.json",          # 회사채 미상환 잔액
    "cp": "entrprsBilScritsNrdmpBlce.json",  # 기업어음증권 미상환 잔액
    "stb": "srtpdPsndbtNrdmpBlce.json",      # 단기사채 미상환 잔액
}
CLS_NAME = {"Y": "유가", "K": "코스닥", "N": "코넥스", "E": "비상장"}
REPORT_RE = re.compile(r"(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)")


def periodic_filings(months: int = 12) -> list[dict]:
    """정기공시 목록 (검색기간 제한이 3개월이라 나눠서 조회)."""
    out, end = [], date.today()
    start = end - timedelta(days=months * 31)
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=88), end)
        page = 1
        while True:
            d = dart.call("list.json", bgn_de=cur.strftime("%Y%m%d"),
                          end_de=nxt.strftime("%Y%m%d"), pblntf_ty="A",
                          page_no=page, page_count=100)
            out.extend(d.get("list", []))
            if page >= int(d.get("total_page", 1) or 1):
                break
            page += 1
        cur = nxt + timedelta(days=1)
    return out


def parse_report(f: dict) -> dict | None:
    m = REPORT_RE.search(f.get("report_nm", ""))
    if not m:
        return None
    kind, y, mo = m.group(1), int(m.group(2)), int(m.group(3))
    return {"kind": kind, "year": y, "month": mo,
            "rcept_no": f["rcept_no"], "rcept_dt": f.get("rcept_dt", "")}


def reprt_code(rep: dict, fye: int) -> str:
    """보고서 종류 + 결산월 → DART reprt_code"""
    if rep["kind"] == "사업":
        return dart.REPRT["FY"]
    if rep["kind"] == "반기":
        return dart.REPRT["H1"]
    gap = (rep["month"] - fye) % 12  # 결산월 이후 몇 개월째 분기인지
    return dart.REPRT["Q1"] if gap <= 4 else dart.REPRT["Q3"]


def balance(endpoint: str, corp_code: str, year: int, code: str) -> float | None:
    """미상환 잔액 합계(원). 보고서에 표가 없으면 None."""
    rows = dart.call(endpoint, corp_code=corp_code, bsns_year=str(year),
                     reprt_code=code).get("list", [])
    if not rows:
        return None
    # '합계' 행의 합계(sm) 우선, 없으면 행별 sm 최대값
    tot = [r for r in rows if "합계" in (r.get("remndr_exprtn2") or "")]
    vals = [dart.to_num(r.get("sm")) for r in (tot or rows)]
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else 0.0


def main() -> None:
    names = dart.corp_codes()
    print(f"고유번호 {len(names):,}개")

    filings = periodic_filings()
    print(f"정기공시 {len(filings):,}건")

    corps: dict[str, dict] = {}
    for f in filings:
        rep = parse_report(f)
        if not rep:
            continue
        c = corps.setdefault(f["corp_code"], {"cls": f.get("corp_cls", "E"), "reps": []})
        c["reps"].append(rep)

    prev = dart.load_json("universe.json", {"companies": {}})["companies"]
    out: dict[str, dict] = {}
    todo = []
    for cc, c in corps.items():
        reps = sorted(c["reps"], key=lambda r: r["rcept_no"], reverse=True)
        fy = [r for r in reps if r["kind"] == "사업"]
        fye = fy[0]["month"] if fy else 12
        latest = reps[0]
        info = names.get(cc, {})
        rec = {
            "name": info.get("name") or cc,
            "stock_code": info.get("stock_code", ""),
            "cls": c["cls"],
            "fye": fye,
        }
        old = prev.get(cc) or {}
        # 이전 결과는 일단 유지 (이번에 새로 확인하면 덮어씀)
        for k in ("bal", "bal_asof", "checked_rcept"):
            if k in old:
                rec[k] = old[k]
        if not (old.get("checked_rcept") == latest["rcept_no"] and "bal" in old):
            todo.append((cc, latest, fye))
        out[cc] = rec

    # 새 보고서만 병렬 조회. 시간 예산을 넘기면 멈추고 저장 → 다음 실행에서 이어서.
    deadline = time.monotonic() + BUDGET_MIN * 60
    stop = threading.Event()

    def work(item):
        if stop.is_set() or time.monotonic() > deadline:
            return None
        cc, latest, fye = item
        code = reprt_code(latest, fye)
        bal = {k: balance(ep, cc, latest["year"], code) for k, ep in BAL_APIS.items()}
        return cc, latest, bal

    print(f"잔액 조회 대상 {len(todo):,}개사 (캐시 {len(out) - len(todo):,}개사), "
          f"병렬 {WORKERS}, 시간 예산 {BUDGET_MIN}분")
    done = failed = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(work, it) for it in todo]
        for f in as_completed(futs):
            try:
                r = f.result()
            except dart.DartLimitError as e:
                if not stop.is_set():
                    print(f"중단: {e}", file=sys.stderr)
                stop.set()
                continue
            except Exception as e:  # 한 회사 실패는 건너뛰고 다음 실행에서 재시도
                failed += 1
                continue
            if r is None:
                continue
            cc, latest, bal = r
            out[cc].update(bal=bal, bal_asof=f'{latest["year"]}.{latest["month"]:02d}',
                           checked_rcept=latest["rcept_no"])
            done += 1
            if done % 200 == 0:
                print(f"  {done:,}/{len(todo):,}")
    left = len(todo) - done
    calls_done = done * len(BAL_APIS)
    if left:
        print(f"미확인 {left:,}개사 (실패 {failed:,}) — 다음 실행에서 이어서 조회")

    for rec in out.values():
        b = rec.get("bal") or {}
        rec["issuer"] = [k for k, v in b.items() if v and v > 0]
        rec["listed"] = rec["cls"] in ("Y", "K", "N")
        rec["target"] = rec["listed"] or bool(rec["issuer"])

    targets = {k: v for k, v in out.items() if v["target"]}
    dart.save_json("universe.json", {
        "updated": date.today().isoformat(),
        "cls_name": CLS_NAME,
        "companies": out,
    }, compact=True)
    n_iss = sum(1 for v in out.values() if v["issuer"])
    print(f"정기공시 기업 {len(out):,} / 대상 {len(targets):,} "
          f"(발행사 {n_iss:,}) / 이번 잔액 조회 {calls_done:,}회")


if __name__ == "__main__":
    main()
