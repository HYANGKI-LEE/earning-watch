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
BV = 2  # 잔액 구조 버전 — 2: 회사채를 공모/사모로 나눠 저장 (발행사 = 공모 회사채만). 이전 버전은 다시 조회
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


def rdate(rep: dict) -> date:
    """접수번호 앞 8자리 = 접수일"""
    s = rep["rcept_no"]
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


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


def bond_split(corp_code: str, year: int, code: str) -> dict | None:
    """회사채 미상환 잔액을 공모/사모로 → {"pub", "priv", "all"(, "est")} (원). 표가 없으면 None.

    발행사 리스트는 공모 회사채만 센다 (사모사채·사모 CB/BW 제외).
    공모/사모 행 없이 '합계'만 있는 보고서는 채무증권 발행실적(미상환 건의 공모/사모)으로 판단.
    """
    rows = dart.call(BAL_APIS["bond"], corp_code=corp_code, bsns_year=str(year),
                     reprt_code=code).get("list", [])
    if not rows:
        return None
    lab = lambda r: (r.get("remndr_exprtn2") or "").replace(" ", "")

    def total(word):
        vals = [dart.to_num(r.get("sm")) for r in rows if word in lab(r)]
        return sum(v for v in vals if v is not None)

    has_pub = any("공모" in lab(r) for r in rows)
    has_priv = any("사모" in lab(r) for r in rows)
    tots = [dart.to_num(r.get("sm")) for r in rows if "합계" in lab(r)]
    tots = [v for v in tots if v is not None]
    if has_pub or has_priv:
        pub, priv = total("공모"), total("사모")
        return {"pub": pub, "priv": priv, "all": max(tots) if tots else pub + priv}
    vals = [v for v in (dart.to_num(r.get("sm")) for r in rows) if v is not None]
    tot = max(tots or vals or [0.0])
    if not tot:
        return {"pub": 0.0, "priv": 0.0, "all": 0.0}
    iss = dart.call("detScritsIsuAcmslt.json", corp_code=corp_code, bsns_year=str(year),
                    reprt_code=code).get("list", [])
    live = [r for r in iss if "사채" in (r.get("scrits_knd_nm") or "")
            and any(w in (r.get("repy_at") or "") for w in ("미", "일부"))]
    pub_live = any("공모" in (r.get("isu_mth_nm") or "") for r in live)
    priv_live = any("사모" in (r.get("isu_mth_nm") or "") for r in live)
    if priv_live and not pub_live:
        return {"pub": 0.0, "priv": tot, "all": tot}
    if pub_live and not priv_live:
        return {"pub": tot, "priv": 0.0, "all": tot}
    # 공모·사모 섞임 또는 판단 불가 → 합계를 공모로 두고 '추정' 표시
    return {"pub": tot, "priv": 0.0, "all": tot, "est": 1}


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
        # 직전 보고서(다른 기간) — 최신 보고서에 잔액 표가 없을 때 대신 조회
        prev_rep = next((r for r in reps if (r["year"], r["month"]) != (latest["year"], latest["month"])), None)
        old = prev.get(cc) or {}
        # 이전 결과는 일단 유지 (이번에 새로 확인하면 덮어씀)
        for k in ("bal", "bal_asof", "checked_rcept", "bv"):
            if k in old:
                rec[k] = old[k]
        # 최신 보고서 기준 값이 아니면(표 미반영 등) 제출 후 30일까지 매 실행 재확인
        stale = old.get("bal_asof") != f'{latest["year"]}.{latest["month"]:02d}'
        no_table = "bal" in old and all(v is None for v in (old["bal"] or {}).values())
        fresh = (date.today() - rdate(latest)).days <= 30
        # 구조 버전이 옛날이고 회사채 잔액이 있던 회사 → 공모/사모 분리를 위해 다시 조회
        old_ver = old.get("bv") != BV and bool((old.get("bal") or {}).get("bond"))
        if (old.get("checked_rcept") != latest["rcept_no"] or "bal" not in old
                or ((stale or no_table) and fresh) or old_ver):
            todo.append((cc, latest, prev_rep, fye))
        out[cc] = rec

    # 새 보고서만 병렬 조회. 시간 예산을 넘기면 멈추고 저장 → 다음 실행에서 이어서.
    deadline = time.monotonic() + BUDGET_MIN * 60
    stop = threading.Event()

    def work(item):
        if stop.is_set() or time.monotonic() > deadline:
            return None
        cc, latest, prev_rep, fye = item

        def query(rep):
            code = reprt_code(rep, fye)
            b = bond_split(cc, rep["year"], code)
            res = {"bond": b["pub"] if b else None,
                   "bond_priv": b["priv"] if b else None,
                   "bond_all": b["all"] if b else None}
            if b and b.get("est"):
                res["bond_est"] = 1
            res.update({k: balance(ep, cc, rep["year"], code) for k, ep in BAL_APIS.items() if k != "bond"})
            return res

        bal, used = query(latest), latest
        if all(v is None for v in bal.values()) and prev_rep:
            # 최신 보고서에 잔액 표가 아직 없으면 직전 보고서 기준으로
            pb = query(prev_rep)
            if any(v is not None for v in pb.values()):
                bal, used = pb, prev_rep
        return cc, latest, used, bal

    print(f"잔액 조회 대상 {len(todo):,}개사 (캐시 {len(out) - len(todo):,}개사), "
          f"병렬 {WORKERS}, 시간 예산 {BUDGET_MIN}분")
    done = failed = pending_tbl = 0
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
            cc, latest, used, bal = r
            done += 1
            if all(v is None for v in bal.values()):
                # 최신·직전 보고서 모두 잔액 표 없음 → 이전 값 유지
                if "bal" not in out[cc] or out[cc].get("bv") != BV:
                    out[cc]["bal"] = bal  # 옛 구조(회사채=공모+사모 합계) 값은 남기지 않음
                out[cc]["checked_rcept"] = latest["rcept_no"]
                out[cc]["bv"] = BV
            else:
                if used is not latest:
                    pending_tbl += 1  # 최신 보고서 표 미반영 → 직전 보고서 값, 30일간 재확인
                out[cc].update(bal=bal, bal_asof=f'{used["year"]}.{used["month"]:02d}',
                               checked_rcept=latest["rcept_no"], bv=BV)
            if done % 200 == 0:
                print(f"  잔액 조회 {done:,}/{len(todo):,} ({done / len(todo):.0%})", flush=True)
    if pending_tbl:
        print(f"최신 보고서 잔액 표 미반영 {pending_tbl:,}개사 — 직전 보고서 기준으로 표시")
    left = len(todo) - done
    calls_done = done * len(BAL_APIS)  # 대략 (직전 보고서·발행실적 추가 조회 제외)
    if left:
        print(f"미확인 {left:,}개사 (실패 {failed:,}) — 다음 실행에서 이어서 조회")

    for rec in out.values():
        b = rec.get("bal") or {}
        rec["issuer"] = [k for k in BAL_APIS if b.get(k) and b[k] > 0]  # bond = 공모 회사채
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
