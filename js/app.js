// data/ 의 JSON만 읽는다 (API 직접 호출 금지)
fetch("data/meta.json", { cache: "no-store" })
  .then(r => r.ok ? r.json() : Promise.reject(r.status))
  .then(meta => {
    document.getElementById("status").textContent = `마지막 갱신: ${meta.updated_at}`;
  })
  .catch(() => {
    document.getElementById("status").textContent = "아직 수집된 데이터가 없어요.";
  });
