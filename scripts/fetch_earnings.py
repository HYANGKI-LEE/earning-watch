"""분기 실적 수집 (DART 다중회사 주요계정 fnlttMultiAcnt).

대상: data/universe.json 의 target 기업 (상장사 ∪ 회사채/CP/전단채 발행사)
기간: 최근 6개 분기 (YoY·QoQ 계산용)
손익은 '분기 단독' 값으로 저장 (4Q = 연간 − 3Q 누적).

결과: data/earnings.json
"""
from __future__ import annotations

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import dart

WORKERS = int(os.environ.get("DART_WORKERS", "10"))

# 분기 번호 → reprt_code
Q_CODE = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
FLOW = ("rev", "op", "ni")      # 손익(기간) 항목
STOCK = ("asset", "liab", "eq")  # 재무상태(시점) 항목

ALIAS = {
    "매출액": "rev", "수익": "rev", "영업수익": "rev", "매출": "rev",
    "영업이익": "op",
    "당기순이익": "ni", "분기순이익": "ni", "반기순이익": "ni",
    "자산총계": "asset", "부채총계": "liab", "자본총계": "eq",
}


def norm(name: str) -> str | None:
    s = re.sub(r"\(.*?\)", "", name or "").replace(" ", "")
    return ALIAS.get(s)


def recent_quarters(n: int = 6, today: date | None = None) -> list[tuple[int, int]]:
    """공시 시점 기준 최근 n개 분기 [(연도, 분기)] 과거→최신.
    분기보고서 마감(45일)·사업보고서(90일)를 감안해 '이미 공시가 시작된' 분기까지."""
    t = today or date.today()
    # 분기 종료 후 약 30일이 지나면 그 분기를 최신으로 본다 (잠정 공시 반영)
    y, m = t.year, t.month
    q = (m - 2) // 3  # 11월 → 3Q, 2월 → 4Q(전년), 5월 → 1Q, 8월 → 2Q
    if q <= 0:
        y, q = y - 1, 4 + q
    out = []
    for _ in range(n):
        out.append((y, q))
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out[::-1]


def fetch_period(codes: list[str], year: int, q: int) -> dict[str, dict]:
    """한 분기의 모든 대상 기업 주요계정 → {corp_code: {CFS: {...}, OFS: {...}, rcept_no}}"""
    res: dict[str, dict] = {}
    chunks = [codes[i:i + 100] for i in range(0, len(codes), 100)]

    def get(chunk):
        return dart.call("fnlttMultiAcnt.json", corp_code=",".join(chunk),
                         bsns_year=str(year), reprt_code=Q_CODE[q]).get("list", [])

    # 100개사 묶음 호출을 병렬로 (전체 속도는 dart.RATE 로 제한)
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(get, chunks))
    for rows in results:
        for r in rows:
            key = norm(r.get("account_nm", ""))
            if not key:
                continue
            c = res.setdefault(r["corp_code"], {"rcept_no": r.get("rcept_no", "")})
            fs = c.setdefault(r.get("fs_div", "OFS"), {})
            if key in fs:  # 같은 계정 중복 시 첫 값 유지
                continue
            fs[key] = {
                "amt": dart.to_num(r.get("thstrm_amount")),
                "add": dart.to_num(r.get("thstrm_add_amount")),
            }
    return res


def main() -> None:
    uni = dart.load_json("universe.json", None)
    if not uni:
        raise SystemExit("data/universe.json 이 없어요. build_universe.py 를 먼저 실행하세요.")
    targets = {k: v for k, v in uni["companies"].items() if v.get("target")}
    codes = sorted(targets)
    quarters = recent_quarters()
    print(f"대상 {len(codes):,}개, 분기 {quarters}")

    raw: dict[tuple[int, int], dict] = {}
    try:
        for y, q in quarters:
            raw[(y, q)] = fetch_period(codes, y, q)
            print(f"  {y}Q{q}: {len(raw[(y, q)]):,}개사")
    except dart.DartLimitError as e:
        print(f"중단: {e}", file=sys.stderr)
        if not raw:
            sys.exit(1)

    companies: dict[str, dict] = {}
    for cc in codes:
        # 연결(CFS) 우선, 없으면 별도(OFS) — 기업 단위로 하나로 통일
        has_cfs = any("CFS" in raw[p].get(cc, {}) for p in raw)
        fsd = "CFS" if has_cfs else "OFS"
        d = {}
        for (y, q), per in raw.items():
            c = per.get(cc)
            if not c or fsd not in c:
                continue
            fs = c[fsd]
            v = {"dt": c["rcept_no"][:8]}
            for k in FLOW:
                if k not in fs:
                    continue
                amt, add = fs[k]["amt"], fs[k]["add"]
                if q == 4:
                    # 사업보고서는 연간값 → 3Q 누적을 빼서 4Q 단독
                    prev = raw.get((y, 3), {}).get(cc, {}).get(fsd, {}).get(k, {})
                    cum3 = prev.get("add") if prev else None
                    v[k] = amt - cum3 if (amt is not None and cum3 is not None) else None
                    v["c" + k] = amt
                else:
                    v[k] = amt
                    v["c" + k] = add if add is not None else (amt if q == 1 else None)
            for k in STOCK:
                if k in fs:
                    v[k] = fs[k]["amt"]
            d[f"{y}Q{q}"] = v
        if d:
            companies[cc] = {"fs": fsd, "d": d}

    dart.save_json("earnings.json", {
        "updated": date.today().isoformat(),
        "periods": [f"{y}Q{q}" for y, q in quarters],
        "companies": companies,
    }, compact=True)
    print(f"실적 저장: {len(companies):,}개사")


if __name__ == "__main__":
    main()
