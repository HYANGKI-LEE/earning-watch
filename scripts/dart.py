"""DART OpenAPI 공통 클라이언트.

- 키는 환경변수 DART_API_KEY 로만 받는다 (GitHub Secrets / 로컬 .env).
- 키 값은 절대 출력·저장하지 않는다.
"""
from __future__ import annotations

import io
import json
import os
import time
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BASE = "https://opendart.fss.or.kr/api/"

# DART 보고서 코드
REPRT = {"Q1": "11013", "H1": "11012", "Q3": "11014", "FY": "11011"}

import threading

# 전체 호출 속도 상한 (여러 스레드가 동시에 불러도 합쳐서 초당 RATE 건)
RATE = float(os.environ.get("DART_RATE", "10"))
_lock = threading.Lock()
_next = [0.0]


def _throttle() -> None:
    with _lock:
        now = time.monotonic()
        t = max(now, _next[0])
        _next[0] = t + 1.0 / RATE
    if t > now:
        time.sleep(t - now)


class DartLimitError(RuntimeError):
    """일일 호출 한도 초과(020) 등 더 진행하면 안 되는 오류."""


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api_key() -> str:
    _load_dotenv()
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        raise SystemExit("DART_API_KEY 가 없어요 (GitHub Secrets 또는 로컬 .env 에 설정).")
    return key


def _get(url: str, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "earning-watch"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # 네트워크 일시 오류 재시도
            last = e
            time.sleep(2 * (i + 1))
    # 키가 들어간 URL 은 출력하지 않는다
    raise RuntimeError(f"요청 실패: {type(last).__name__}")


def call(endpoint: str, **params) -> dict:
    """JSON API 호출. status 000 이면 dict, 013(데이터 없음)이면 빈 list 를 가진 dict."""
    params = {"crtfc_key": api_key(), **params}
    url = BASE + endpoint + "?" + urllib.parse.urlencode(params)
    _throttle()
    data = json.loads(_get(url).decode("utf-8"))
    status = data.get("status")
    if status == "000":
        return data
    if status == "013":  # 조회된 데이터 없음
        return {"status": "013", "list": []}
    if status in ("010", "011", "012", "020", "901"):
        # 010 미등록키, 011 사용불가키, 012 접근불가 IP, 020 요청제한 초과, 901 키 만료
        raise DartLimitError(f"DART 오류 {status}: {data.get('message')}")
    raise RuntimeError(f"DART 오류 {status}: {data.get('message')} ({endpoint})")


def corp_codes() -> dict[str, dict]:
    """전체 고유번호(corpCode.xml) → {corp_code: {name, stock_code}}"""
    url = BASE + "corpCode.xml?" + urllib.parse.urlencode({"crtfc_key": api_key()})
    raw = _get(url)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xml = z.read(z.namelist()[0])
    out = {}
    for el in ET.fromstring(xml).iter("list"):
        code = (el.findtext("corp_code") or "").strip()
        out[code] = {
            "name": (el.findtext("corp_name") or "").strip(),
            "stock_code": (el.findtext("stock_code") or "").strip(),
        }
    return out


def to_num(v) -> float | None:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def load_json(name: str, default):
    p = DATA_DIR / name
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return default


def save_json(name: str, obj, compact: bool = False) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    text = (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            if compact else json.dumps(obj, ensure_ascii=False, indent=1))
    (DATA_DIR / name).write_text(text, encoding="utf-8")
