"""원본 응답 확인용: debug/request.txt 의 기업코드별로 잔액 API 원본을 그대로 저장.
결과: debug/raw.json (키는 저장하지 않음)"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import dart

APIS = {"bond": "cprndNrdmpBlce.json", "cp": "entrprsBilScritsNrdmpBlce.json",
        "stb": "srtpdPsndbtNrdmpBlce.json"}
REPS = [("2026", "11014"), ("2025", "11011")]  # 2026 3분기, 2025 사업보고서
here = Path(__file__).resolve().parent
codes = [l.strip() for l in (here / "request.txt").read_text().splitlines() if l.strip()]
out = {}
for cc in codes:
    for y, rc in REPS:
        for k, ep in APIS.items():
            out.setdefault(cc, {}).setdefault(f"{y}_{rc}", {})[k] = dart.call(
                ep, corp_code=cc, bsns_year=y, reprt_code=rc).get("list", [])
(here / "raw.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("저장:", {cc: {r: {k: len(v) for k, v in d.items()} for r, d in x.items()} for cc, x in out.items()})
