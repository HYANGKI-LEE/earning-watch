"""데이터 수집 스크립트 (뼈대).

API 키는 환경변수로만 받는다 (GitHub Actions Secrets -> env).
실제 API 호출은 데이터 소스가 정해지면 채운다.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
KST = timezone(timedelta(hours=9))


def main() -> None:
    api_key = os.environ.get("API_KEY")  # 키 값은 절대 출력하지 않는다
    DATA_DIR.mkdir(exist_ok=True)

    meta = {
        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "api_key_configured": bool(api_key),
    }
    (DATA_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("meta.json 갱신:", meta["updated_at"])


if __name__ == "__main__":
    main()
