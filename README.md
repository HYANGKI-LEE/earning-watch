# earning-watch

회사채·CP 발행사와 상장사의 분기 실적 발표를 모아 보는 대시보드.

## 구조

```
GitHub Actions (키는 Secrets에 보관)
  → scripts/fetch_data.py 가 API 호출 → data/*.json 생성 → 커밋
      → GitHub Pages (index.html) 가 JSON 을 읽어 표시
```

- `index.html`, `js/`, `css/` : 정적 페이지 (GitHub Pages)
- `scripts/` : 데이터 수집 스크립트 (Actions에서 실행)
- `data/` : 수집 결과 JSON (페이지가 읽는 파일)
- `.github/workflows/update-data.yml` : 수집 → 커밋 자동화

## 보안 원칙 (public 레포)

- API 키는 코드·커밋에 넣지 않는다. 레포 **Settings → Secrets and variables → Actions** 에만 저장.
- 페이지(브라우저)에서 API를 직접 호출하지 않는다. 페이지는 `data/` 의 가공된 JSON만 읽는다.
