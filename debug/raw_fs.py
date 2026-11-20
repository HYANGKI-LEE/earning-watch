"""재무제표 API 원본 확인용: 왜 일부 회사는 분기 실적이 비는지 (연결/별도, 보고서 유무).
대상: debug/fs_request.txt  결과: debug/raw_fs.json (키는 저장하지 않음)"""
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import dart

here = Path(__file__).resolve().parent
codes = [l.split()[0] for l in (here / "fs_request.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
REPS = [("2026", "11014"), ("2026", "11012"), ("2025", "11011")]
out = {}
for cc in codes:
    o = out[cc] = {}
    for y, rc in REPS:
        m = dart.call("fnlttMultiAcnt.json", corp_code=cc, bsns_year=y, reprt_code=rc).get("list", [])
        o[f"multi_{y}_{rc}"] = dict(Counter(r.get("fs_div") for r in m))
        for div in ("CFS", "OFS"):
            s = dart.call("fnlttSinglAcntAll.json", corp_code=cc, bsns_year=y, reprt_code=rc, fs_div=div).get("list", [])
            o[f"all_{y}_{rc}_{div}"] = len(s)
    # 최근 정기공시 목록 (보고서 이름·제출일)
    l = dart.call("list.json", corp_code=cc, bgn_de="20260101", end_de="20261120", pblntf_ty="A", page_count="20").get("list", [])
    o["reports"] = [f"{r.get('rcept_dt')} {r.get('report_nm', '').strip()}" for r in l]
    c = dart.call("company.json", corp_code=cc)
    o["corp"] = {k: c.get(k) for k in ("corp_name", "corp_cls", "acc_mt")}
(here / "raw_fs.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("저장", len(out))
