# earning-watch

회사채·CP 발행사와 상장사의 분기 실적 발표를 모아 보는 대시보드.

## 구조

```
GitHub Actions (키는 Secrets에 보관)
  → scripts/build_universe.py : 정기공시 기업의 회사채·CP·전단채 미상환 잔액 확인 → data/universe.json
  → scripts/fetch_earnings.py : 대상(상장사 ∪ 발행사) 최근 6개 분기 주요계정 → data/earnings.json
  → 커밋
      → GitHub Pages (index.html) 가 JSON 을 읽어 표시
```

- `index.html`, `js/`, `css/` : 정적 페이지 (GitHub Pages)
- `scripts/` : 데이터 수집 스크립트 (Actions에서 실행, 키는 환경변수 `DART_API_KEY`)
  - 로컬 테스트: 레포 폴더에 `.env` 파일(`DART_API_KEY=...`) — gitignore 됨
- `data/` : 수집 결과 JSON (페이지가 읽는 파일)
- `.github/workflows/update-data.yml` : 수집 → 커밋 자동화

## 보안 원칙 (public 레포)

- API 키는 코드·커밋에 넣지 않는다. 레포 **Settings → Secrets and variables → Actions** 에만 저장.
- 페이지(브라우저)에서 API를 직접 호출하지 않는다. 페이지는 `data/` 의 가공된 JSON만 읽는다.
