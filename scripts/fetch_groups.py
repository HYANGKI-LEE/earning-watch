"""공시대상기업집단 소속회사 명단 (공정위 기업집단포털 > 소속회사 개요).

지정일(매년 5월) 기준이라 1년에 한 번 수동 실행: python scripts/fetch_groups.py 202605
DART 키는 쓰지 않는다. DART 회사와는 법인등록번호(company.json 의 jurir_no)로 연결한다.

결과: data/groups.json — groups: {그룹명: [[회사명, 법인등록번호, 구분(일반/금융보험), 자산총액(백만원)], ...]}
"""
from __future__ import annotations

import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser

import dart

URL = "https://www.egroup.go.kr/egps/ps/io/kap/selectAjaxPsitnCmpnySumryList.do"
COLS = {"grp": "기업집단명", "name": "소속회사명", "kind": "구분", "jur": "법인등록번호", "asset": "자산총액"}


class Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cell = [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th") and self.rows:
            self.rows[-1].append("")
            self.cell = True

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.cell = False

    def handle_data(self, data):
        if self.cell and self.rows and self.rows[-1]:
            self.rows[-1][-1] += data


def page(ym: str, i: int) -> list[list[str]]:
    body = urllib.parse.urlencode({
        "pageIndex": i, "pageUnit": 1000, "sch_unityGrupId": "ALL", "sch_unityGrupNm": "", "sch_entrprsId": "",
        "sch_entrprsNm": "", "sch_othbcYm": "", "sch_startYm": ym, "sch_endYm": ym, "sch_applYear": ym[:4]}).encode()
    req = urllib.request.Request(URL, body, {"User-Agent": "Mozilla/5.0"})
    t = Table()
    t.feed(urllib.request.urlopen(req, timeout=90).read().decode("utf-8"))
    return [[re.sub(r"\s+", " ", c).strip() for c in r] for r in t.rows if len(r) > 10]


def main(ym: str) -> None:
    groups: dict[str, list] = {}
    n = 0
    for i in range(1, 20):
        rows = page(ym, i)
        head, body = rows[0] if rows else [], rows[1:]
        if not body or COLS["jur"] not in head:
            break
        ix = {k: head.index(v) for k, v in COLS.items()}
        for r in body:
            asset = dart.to_num(r[ix["asset"]])
            groups.setdefault(r[ix["grp"]], []).append(
                [r[ix["name"]], re.sub(r"\D", "", r[ix["jur"]]), r[ix["kind"]], asset])
        n += len(body)
        if len(body) < 1000:
            break
        time.sleep(1)
    if n < 1000:
        raise SystemExit(f"명단이 너무 적음({n}건) — 화면 구조가 바뀌었는지 확인 필요, 저장 안 함")
    dart.save_json("groups.json", {
        "asof": ym, "fetched": date.today().isoformat(),
        "source": "공정거래위원회 기업집단포털 소속회사 개요",
        "groups": dict(sorted(groups.items())),
    }, compact=True)
    print(f"그룹 {len(groups)}개, 소속회사 {n:,}건")


if __name__ == "__main__":
    main(sys.argv[1])
