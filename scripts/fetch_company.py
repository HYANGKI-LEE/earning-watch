"""기업개황 수집 (DART company.json) — 업종코드 등 회사 기본 정보.

대상: data/universe.json 의 전체 기업 (발행사 리스트와 같음)
- 이미 받은 회사는 REFRESH_DAYS 가 지나기 전엔 다시 부르지 않는다 (새 회사만 조회).
- induty_code = 한국표준산업분류(KSIC 제11차) 코드. 업종명은 API 에 없어서
  data/ksic11.json(통계분류포털 분류표)으로 붙인다: induty_name + 대·중분류.
  (분류표만으로 다시 붙이기: python scripts/fetch_company.py --names — API 호출 없음)

결과: data/company.json
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import dart

WORKERS = int(os.environ.get("DART_WORKERS", "10"))
REFRESH_DAYS = int(os.environ.get("COMPANY_REFRESH_DAYS", "90"))
BUDGET_MIN = float(os.environ.get("COMPANY_BUDGET_MIN", "60"))

# 저장할 항목 (API 응답 필드 그대로)
FIELDS = ("corp_name", "corp_name_eng", "stock_name", "stock_code", "ceo_nm", "corp_cls",
          "jurir_no", "bizr_no", "adres", "hm_url", "ir_url", "phn_no", "fax_no",
          "induty_code", "est_dt", "acc_mt")


def add_names(companies: dict) -> int:
    """업종코드 → 업종명, 대분류(A~U), 중분류(2자리) 이름"""
    K = dart.load_json("ksic11.json", {"codes": {}})["codes"]
    n = 0
    for v in companies.values():
        code = v.get("induty_code", "")
        chain, c = [], code
        while c in K:          # 위로 거슬러 올라가며 [코드, 이름] 모으기
            chain.append([c, K[c][0]])
            c = K[c][1]
        chain.reverse()        # 대분류 → … → 해당 코드
        v["induty_name"] = chain[-1][1] if chain else ""
        v["ind_sec"] = f"{chain[0][0]}.{chain[0][1]}" if chain else ""                    # 대분류
        v["ind_div"] = f"{chain[1][0]}.{chain[1][1]}" if len(chain) > 1 else ""           # 중분류
        n += bool(chain)
    return n


def names_only() -> None:
    doc = dart.load_json("company.json", None)
    if not doc:
        raise SystemExit("data/company.json 이 없어요.")
    n = add_names(doc["companies"])
    dart.save_json("company.json", doc, compact=True)
    print(f"업종명 매칭 {n:,}/{len(doc['companies']):,}개사")


def main() -> None:
    uni = dart.load_json("universe.json", None)
    if not uni:
        raise SystemExit("data/universe.json 이 없어요.")
    prev = dart.load_json("company.json", {"companies": {}})["companies"]
    today = date.today()

    def due(cc):
        at = (prev.get(cc) or {}).get("_at")
        return not at or (today - date.fromisoformat(at)).days >= REFRESH_DAYS

    todo = [cc for cc in sorted(uni["companies"]) if due(cc)]
    print(f"기업개황 대상 {len(todo):,}개사 (저장됨 {len(prev):,}), 병렬 {WORKERS}", flush=True)

    deadline = time.monotonic() + BUDGET_MIN * 60
    stop = [False]

    def work(cc):
        if stop[0] or time.monotonic() > deadline:
            return None
        return cc, dart.call("company.json", corp_code=cc)

    out = dict(prev)
    done = failed = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for f in as_completed([ex.submit(work, cc) for cc in todo]):
            try:
                r = f.result()
            except dart.DartLimitError as e:
                if not stop[0]:
                    print(f"중단: {e}", file=sys.stderr, flush=True)
                stop[0] = True
                continue
            except Exception:
                failed += 1
                continue
            if r is None:
                continue
            cc, d = r
            if d.get("status") != "000":  # 013 등 — 다음 실행에서 재시도
                failed += 1
                continue
            out[cc] = {k: (d.get(k) or "").strip() for k in FIELDS} | {"_at": today.isoformat()}
            done += 1
            if done % 500 == 0:
                print(f"  기업개황 {done:,}/{len(todo):,}", flush=True)

    print(f"업종명 매칭 {add_names(out):,}/{len(out):,}개사", flush=True)
    dart.save_json("company.json", {
        "updated": today.isoformat(),
        "companies": dict(sorted(out.items())),
    }, compact=True)
    print(f"기업개황 저장: 이번 {done:,}개사 (실패 {failed:,}, 남음 {len(todo) - done - failed:,}) "
          f"/ 누적 {len(out):,}개사", flush=True)


if __name__ == "__main__":
    names_only() if "--names" in sys.argv else main()
