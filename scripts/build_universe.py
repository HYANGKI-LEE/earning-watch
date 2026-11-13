"""대상 기업 목록(universe) 만들기.

1) 최근 12개월 정기공시(사업/반기/분기보고서) 제출 기업을 모은다.
2) 각 기업의 최신 정기보고서에서
   회사채 / 기업어음(CP) / 단기사채(전단채) 미상환 잔액을 조회한다.
3) 상장사(유가·코스닥·코넥스) 또는 미상환 잔액 > 0 인 기업을 대상으로 한다.

결과: data/universe.json
  - 이미 확인한 보고서(rcept_no)는 다시 조회하지 않는다 (호출 수 절약).
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta

import dart

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
    calls_done = 0
    try:
        for i, (cc, c) in enumerate(corps.items(), 1):
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
                "checked_rcept": latest["rcept_no"],
            }
            old = prev.get(cc)
            if old and old.get("checked_rcept") == latest["rcept_no"] and "bal" in old:
                rec["bal"], rec["bal_asof"] = old["bal"], old.get("bal_asof")
            else:
                code = reprt_code(latest, fye)
                rec["bal"] = {k: balance(ep, cc, latest["year"], code)
                              for k, ep in BAL_APIS.items()}
                rec["bal_asof"] = f'{latest["year"]}.{latest["month"]:02d}'
                calls_done += len(BAL_APIS)
            out[cc] = rec
            if i % 200 == 0:
                print(f"  {i:,}/{len(corps):,} (신규 조회 {calls_done:,}회)")
    except dart.DartLimitError as e:
        # 한도 초과 시 지금까지 결과 + 이전 결과 보존 후 종료 → 다음 실행에서 이어서
        print(f"중단: {e}", file=sys.stderr)
        for cc, old in prev.items():
            out.setdefault(cc, old)

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
