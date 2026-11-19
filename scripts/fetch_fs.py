"""상세 재무제표 수집 (DART 단일회사 전체 재무제표 fnlttSinglAcntAll) — 단계식.

1) fetch_earnings.py 가 만든 data/earnings.json 에서 회사별 '최신 분기' 보고서 번호(rno)를 본다.
2) data/fs_index.json 에 저장된 rno 와 다르면(새 보고서·정정) 그 회사만 전체 재무제표를 받는다.
   → 처음 한 번은 전체 회사 백필, 그 뒤로는 새로 나온 보고서만 (호출 수 최소).
3) 회사별 파일 data/fs/<corp_code>.json 에 재무상태표·손익·포괄손익·현금흐름표 전 계정 저장
   (자본변동표는 용량이 커서 제외, 회사당 최근 KEEP 개 분기만 보관).
4) 차입금(단기·장기차입금, 사채, 유동성장기부채, 리스부채 등)과 차입금의존도는
   data/fs_index.json 에 모아 화면 표에서 바로 쓴다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from itertools import combinations

import dart

WORKERS = int(os.environ.get("DART_WORKERS", "10"))
MAX_CALLS = int(os.environ.get("FS_MAX_CALLS", "8000"))       # 한 번 실행 호출 상한 (일일 한도 보호)
BUDGET_MIN = float(os.environ.get("FS_BUDGET_MIN", "100"))    # 시간 예산 — 넘으면 저장하고 다음 실행에서 이어서
KEEP = 4                                                      # 회사 파일에 보관할 분기 수
MAX_TRIES = 3                                                 # 데이터 없음(013) 재시도 횟수

Q_CODE = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
SJ_KEEP = ("BS", "IS", "CIS", "CF")
FS_DIR = dart.DATA_DIR / "fs"

# 차입금으로 볼 계정 (재무상태표, 계정명 기준)
BRW_INC = ("차입금", "차입부채", "사채", "리스부채", "유동성장기부채", "기업어음")
BRW_RE = re.compile(r"리스(유동|비유동)?부채")  # '리스유동부채'·'리스비유동부채' 같은 어순
BRW_EXC = ("할인", "할증", "발행비", "미지급이자", "이자비용", "충당", "채권", "대여", "현재가치", "조정", "상환",
           "파생", "전환권", "신주인수권", "선급", "미수", "자산")


def nm(s: str) -> str:
    """계정명 정리: 공백·괄호 주석 제거"""
    return re.sub(r"\(.*?\)|\[.*?\]|\s", "", s or "")


def is_brw(name: str) -> bool:
    n = nm(name)
    return (any(k in n for k in BRW_INC) or bool(BRW_RE.search(n))) and not any(k in n for k in BRW_EXC)


def drop_totals(items: list[list]) -> list[list]:
    """같은 표에 '소계/합계' 행과 그 하위 행이 함께 있으면 이중 계산 → 다른 행들의 합과 같은 행은 소계로 보고 뺀다."""
    items = [it for it in items if it[1]]
    if len(items) > 16:
        return items
    keep = sorted(items, key=lambda x: -abs(x[1]))
    changed = True
    while changed:
        changed = False
        for i, (n_i, a_i) in enumerate(keep):
            others = keep[:i] + keep[i + 1:]
            small = [o for o in others if abs(o[1]) < abs(a_i)]
            found = False
            for k in range(2, len(small) + 1):
                for comb in combinations(small, k):
                    if abs(sum(c[1] for c in comb) - a_i) <= max(1.0, abs(a_i) * 1e-6):
                        found = True
                        break
                if found:
                    break
            if found:
                keep = others
                changed = True
                break
    return keep


def fetch_one(cc: str, year: int, q: int, fs: str) -> tuple[str, list, int]:
    """→ (사용한 fs_div, 행 목록, 호출 수). 연결이 없으면 별도로 재시도."""
    calls = 0
    for div in ([fs, "OFS"] if fs == "CFS" else [fs, "CFS"]):
        calls += 1
        rows = dart.call("fnlttSinglAcntAll.json", corp_code=cc, bsns_year=str(year),
                         reprt_code=Q_CODE[q], fs_div=div).get("list", [])
        if rows:
            return div, rows, calls
    return fs, [], calls


def compact(rows: list) -> dict:
    """API 행 → {BS: [[계정ID, 계정명, 당기금액], ...], IS: [[ID, 이름, 당기(3개월), 누적], ...], ...}"""
    out: dict[str, list] = {}
    for r in rows:
        sj = r.get("sj_div")
        if sj not in SJ_KEEP:
            continue
        aid = r.get("account_id", "")
        if "표준계정코드" in aid:
            aid = ""
        row = [aid, (r.get("account_nm") or "").strip(), dart.to_num(r.get("thstrm_amount"))]
        if sj in ("IS", "CIS"):
            row.append(dart.to_num(r.get("thstrm_add_amount")))
        out.setdefault(sj, []).append(row)
    return out


def summarize(sj: dict) -> dict:
    bs = sj.get("BS", [])
    asset = next((r[2] for r in bs if nm(r[1]) == "자산총계"), None)
    items = drop_totals([[r[1], r[2]] for r in bs if is_brw(r[1]) and r[2] is not None])
    brw = sum(a for _, a in items) if items else 0.0
    dep = brw / asset * 100 if asset else None
    return {"brw": brw, "dep": round(dep, 2) if dep is not None else None,
            "asset": asset, "items": items}


def resummarize() -> None:
    """저장된 회사별 파일로 차입금·차입금의존도만 다시 계산 (API 호출 없음 — 계정 규칙을 바꿨을 때)"""
    idx = dart.load_json("fs_index.json", {"companies": {}})
    n = 0
    for cc, v in idx["companies"].items():
        path = FS_DIR / f"{cc}.json"
        if v.get("na") or not v.get("p") or not path.exists():
            continue
        per = json.loads(path.read_text(encoding="utf-8"))["p"].get(v["p"])
        if per:
            v.update(summarize(per))
            n += 1
    dart.save_json("fs_index.json", idx, compact=True)
    print(f"차입금 재계산 {n:,}개사")


def main() -> None:
    E = dart.load_json("earnings.json", None)
    if not E:
        raise SystemExit("data/earnings.json 이 없어요. fetch_earnings.py 를 먼저 실행하세요.")
    U = dart.load_json("universe.json", {"companies": {}})["companies"]
    idx = dart.load_json("fs_index.json", {"companies": {}})
    I = idx["companies"]

    # 회사별 최신 분기 보고서 → 저장된 것과 다르면 대상
    todo = []
    for cc, c in E["companies"].items():
        ps = [p for p in E["periods"] if p in c["d"]]
        if not ps:
            continue
        p = ps[-1]
        rno = c["d"][p].get("rno")
        if not rno:
            continue
        old = I.get(cc, {})
        if old.get("rno") == rno and (not old.get("na") or old.get("tries", 0) >= MAX_TRIES):
            continue
        todo.append((cc, p, rno, c["fs"]))
    # 회사채·CP 발행사 먼저 → 상장사 → 나머지 (백필이 중간에 멈춰도 중요한 회사부터 채워지게)
    todo.sort(key=lambda t: (not U.get(t[0], {}).get("issuer"), not U.get(t[0], {}).get("listed"), t[0]))
    print(f"상세 재무제표 대상 {len(todo):,}개사 (저장됨 {len(I):,}), 병렬 {WORKERS}, "
          f"호출 상한 {MAX_CALLS:,}, 시간 예산 {BUDGET_MIN:g}분", flush=True)

    FS_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + BUDGET_MIN * 60
    used = [0]
    stop = [False]

    def work(t):
        cc, p, rno, fs = t
        if stop[0] or time.monotonic() > deadline or used[0] + 2 > MAX_CALLS:
            return None
        y, q = int(p[:4]), int(p[-1])
        div, rows, n = fetch_one(cc, y, q, fs)
        used[0] += n
        return t, div, rows

    done = empty = failed = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(work, t) for t in todo]
        for f in as_completed(futs):
            try:
                r = f.result()
            except dart.DartLimitError as e:
                if not stop[0]:
                    print(f"중단: {e}", file=sys.stderr, flush=True)
                stop[0] = True
                continue
            except Exception as e:  # 한 회사 실패는 다음 실행에서 재시도
                failed += 1
                continue
            if r is None:
                continue
            (cc, p, rno, fs), div, rows = r
            done += 1
            if not rows:
                empty += 1
                old = I.get(cc, {})
                tries = old.get("tries", 0) + 1 if old.get("rno") == rno else 1
                # 이전 분기 값은 남겨두되, 이번 보고서는 '아직 없음'으로 표시
                I[cc] = {**{k: v for k, v in old.items() if k not in ("rno", "na", "tries")},
                         "rno": rno, "na": 1, "tries": tries}
                continue
            sj = compact(rows)
            # 회사 파일: 분기별 전 계정 (최근 KEEP 개 분기)
            path = FS_DIR / f"{cc}.json"
            doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"p": {}}
            doc["p"][p] = {"rno": rno, "fs": div, **sj}
            doc["p"] = dict(sorted(doc["p"].items())[-KEEP:])
            path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            I[cc] = {"p": p, "rno": rno, "fs": div, **summarize(sj)}
            if done % 200 == 0:
                print(f"  상세 {done:,}/{len(todo):,} ({done / len(todo):.0%}) 호출 {used[0]:,}", flush=True)

    left = len(todo) - done
    dart.save_json("fs_index.json", {
        "updated": date.today().isoformat(),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "companies": dict(sorted(I.items())),
    }, compact=True)
    print(f"상세 저장: 이번 {done:,}개사 (데이터 없음 {empty:,}, 실패 {failed:,}, 남음 {left:,}) "
          f"/ 호출 {used[0]:,}회 / 누적 {len(I):,}개사", flush=True)


if __name__ == "__main__":
    resummarize() if "--resummarize" in sys.argv else main()
