"""DART 응답 형태 확인용 (공개 데이터만 출력, 키는 출력하지 않음)."""
import json
import sys
import traceback

import dart

out = []
def p(*a):
    out.append(" ".join(str(x) for x in a))

try:
    names = dart.corp_codes()
    p("corps", len(names))
    want = ["삼성전자", "SK하이닉스", "현대캐피탈", "롯데캐피탈", "호텔롯데", "SK"]
    codes = {}
    for k, v in names.items():
        if v["name"] in want and (v["name"] not in codes or v["stock_code"]):
            codes[v["name"]] = k
    p("codes", json.dumps(codes, ensure_ascii=False))

    d = dart.call("list.json", bgn_de="20260801", end_de="20261031", pblntf_ty="A",
                  page_no=1, page_count=5)
    p("list total", d.get("total_count"), d.get("total_page"))
    for r in d.get("list", [])[:5]:
        p("  ", json.dumps(r, ensure_ascii=False))

    for nm in ["현대캐피탈", "롯데캐피탈", "호텔롯데", "삼성전자"]:
        cc = codes.get(nm)
        if not cc:
            continue
        for ep in ["cprndNrdmpBlce.json", "entrprsBilScritsNrdmpBlce.json", "srtpdPsndbtNrdmpBlce.json"]:
            r = dart.call(ep, corp_code=cc, bsns_year="2026", reprt_code="11012")
            p(nm, ep, r.get("status"), len(r.get("list", [])))
            for row in r.get("list", [])[:6]:
                p("    ", json.dumps(row, ensure_ascii=False))

    cs = ",".join(c for c in [codes.get("삼성전자"), codes.get("현대캐피탈")] if c)
    for code in ["11012", "11011"]:
        yr = "2026" if code == "11012" else "2025"
        r = dart.call("fnlttMultiAcnt.json", corp_code=cs, bsns_year=yr, reprt_code=code)
        p("multi", yr, code, r.get("status"), len(r.get("list", [])))
        for row in r.get("list", [])[:30]:
            p("    ", json.dumps({k: row.get(k) for k in (
                "corp_code", "fs_div", "sj_div", "account_nm", "thstrm_nm",
                "thstrm_amount", "thstrm_add_amount", "frmtrm_amount", "rcept_no")}, ensure_ascii=False))
except Exception:
    p("ERROR", traceback.format_exc().replace(dart.os.environ.get("DART_API_KEY", "") or "\0", "***"))


(dart.DATA_DIR / "_probe.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
