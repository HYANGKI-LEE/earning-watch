// data/ 의 JSON만 읽는다 (API 직접 호출 금지)
const $ = s => document.querySelector(s);
const state = { period: null, mode: "q", group: "issuer", inst: new Set(), q: "", sort: { key: "dt", dir: -1 }, open: null };
let U = null, E = null, F = {}, ROWS = []; // F: 상세 재무제표 요약(fs_index.json, 없어도 동작)
let NEW_FROM = ""; // 이 날짜(YYYYMMDD) 이후 접수 공시에 N 표시 = 수집일 + 직전 영업일

// 수집일의 직전 영업일 (월요일 → 금요일). 아침 수집 땐 당일 공시가 아직 없으므로 전날 것도 '새 공시'로
function newFrom(day) {
  if (!day) return "";
  const d = new Date(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10));
  do d.setDate(d.getDate() - 1); while (d.getDay() === 0 || d.getDay() === 6);
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
}

const CLS = { Y: "유가", K: "코스닥", N: "코넥스", E: "비상장" };
const INST = { bond: "회사채", cp: "CP", stb: "전단채" }; // 회사채 = 공모 회사채 잔액
const EOK = 1e8;

const fmt = v => v == null || !isFinite(v) ? "–" : Math.round(v / EOK).toLocaleString("ko-KR");
const pct = v => v == null || !isFinite(v) ? "–" : (v > 0 ? "+" : "") + v.toFixed(1) + "%";
const cls = v => v == null || !isFinite(v) ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
const fmtDt = s => s ? `${s.slice(0, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}` : "–";

function growth(cur, prev) {
  if (cur == null || prev == null || prev === 0) return null;
  if (prev < 0) return null; // 적자 기저는 증감률 의미 없음 → 표시 안 함
  return (cur / prev - 1) * 100;
}
function turn(cur, prev) { // 흑자전환/적자전환/적자지속
  if (cur == null || prev == null) return null;
  if (prev < 0 && cur >= 0) return "흑전";
  if (prev >= 0 && cur < 0) return "적전";
  if (prev < 0 && cur < 0) return "적지";
  return null;
}
// 손익 값: 분기 단독(rev/op/ni) 또는 누적(crev/cop/cni) — 화면 우상단 '분기/누적' 버튼
const pick = (v, k) => v == null ? null : (state.mode === "c" ? v["c" + k] : v[k]) ?? null;
function prevYear(p) { return `${+p.slice(0, 4) - 1}${p.slice(4)}`; }

const COLS = [
  { key: "name", label: "회사명", l: true },
  { key: "link", label: "공시 링크", l: true, nosort: true },
  { key: "cls", label: "상장유형", l: true },
  { key: "inst", label: "발행", l: true, nosort: true },
  { key: "rev", label: "매출" },
  { key: "revY", label: "YoY", g: true },
  { key: "op", label: "영업이익" },
  { key: "opY", label: "YoY", g: true, t: "opT" },
  { key: "opm", label: "영업이익률" },
  { key: "ni", label: "순이익" },
  { key: "niY", label: "YoY", g: true, t: "niT" },
  { key: "debt", label: "부채비율" },
  { key: "dep", label: "차입금의존도" },
  { key: "dt", label: "공시일" },
];

function build() {
  const p = state.period, py = prevYear(p);
  ROWS = [];
  for (const [cc, c] of Object.entries(E.companies)) {
    const v = c.d[p];
    if (!v || !v.rno) continue; // 비교 열로만 채워진 기간(보고서 없음)은 목록에서 제외
    const u = U.companies[cc] || {};
    const y = c.d[py] || {};
    ROWS.push({
      cc, name: u.name || cc, cls: u.cls || "E", listed: !!u.listed, issuer: u.issuer || [],
      bal: u.bal || {}, balAsof: u.bal_asof, fs: c.fs,
      ...(() => {
        const rev = pick(v, "rev"), op = pick(v, "op"), ni = pick(v, "ni");
        const pr = pick(y, "rev"), po = pick(y, "op"), pn = pick(y, "ni");
        return {
          rev, revY: growth(rev, pr),
          op, opY: growth(op, po), opT: turn(op, po),
          opm: rev && op != null ? op / rev * 100 : null,
          ni, niY: growth(ni, pn), niT: turn(ni, pn),
        };
      })(),
      debt: v.eq > 0 ? v.liab / v.eq * 100 : null,
      // 차입금의존도 = 차입금 ÷ 자산총계 (상세 재무제표가 이 분기 것일 때만)
      dep: F[cc] && F[cc].p === p && !F[cc].na ? F[cc].dep : null,
      dt: v.dt, rno: v.rno || "",
      // 같은 날 공시는 접수번호(일련번호) 순서로 최신이 위로
      dtKey: v.rno || v.dt,
      isNew: !!NEW_FROM && v.dt >= NEW_FROM,
    });
  }
}

function filtered() {
  const q = state.q.trim().toLowerCase();
  return ROWS.filter(r => {
    if (state.group === "issuer" && !r.issuer.length) return false;
    if (state.group === "listed" && !r.listed) return false;
    if (state.group === "unlisted-issuer" && (r.listed || !r.issuer.length)) return false;
    for (const i of state.inst) if (!r.issuer.includes(i)) return false;
    if (q && !r.name.toLowerCase().includes(q)) return false;
    return true;
  });
}

function render() {
  const { key, dir } = state.sort;
  const sk = key === "dt" ? "dtKey" : key;
  const rows = filtered().sort((a, b) => {
    const x = a[sk], y = b[sk];
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y, "ko") : x - y) * dir;
  });

  $("#tbl thead").innerHTML = "<tr>" + COLS.map(c =>
    `<th class="${c.l ? "l" : ""}" data-k="${c.nosort ? "" : c.key}">${c.label}${key === c.key ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`
  ).join("") + "</tr>";

  const html = [];
  for (const r of rows.slice(0, 1000)) {
    html.push(`<tr class="row" data-cc="${r.cc}">` + COLS.map(c => {
      if (c.key === "name") return `<td class="l">${r.name}${r.isNew ? '<span class="new" title="최근 공시 (수집일·직전 영업일 접수)">N</span>' : ""}</td>`;
      if (c.key === "link") return `<td class="l">${r.rno ? `<a class="dartlink" href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${r.rno}" target="_blank" rel="noopener">보고서</a>` : "–"}</td>`;
      if (c.key === "cls") return `<td class="l">${CLS[r.cls] || r.cls}</td>`;
      if (c.key === "inst") return `<td class="l">${r.issuer.map(i => `<span class="badge">${INST[i]}</span>`).join("")}</td>`;
      if (c.key === "dt") return `<td>${fmtDt(r.dt)}</td>`;
      if (c.g) {
        const t = c.t && r[c.t];
        if (t) return `<td class="${t === "흑전" ? "up" : "down"}">${t}</td>`;
        return `<td class="${cls(r[c.key])}">${pct(r[c.key])}</td>`;
      }
      if (c.key === "opm" || c.key === "debt" || c.key === "dep") return `<td>${r[c.key] == null ? "–" : r[c.key].toFixed(1) + "%"}</td>`;
      return `<td>${fmt(r[c.key])}</td>`;
    }).join("") + "</tr>");
    if (state.open === r.cc) html.push(detail(r));
  }
  $("#tbl tbody").innerHTML = html.join("");
  // 새 공시 수: 이 필터 안 / 전체 — 다른 필터에 숨은 새 공시도 알 수 있게
  const nNew = rows.filter(r => r.isNew).length, nAll = ROWS.filter(r => r.isNew).length;
  $("#status").textContent = `${state.period}${state.mode === "c" ? " 누적" : ""} · ${rows.length.toLocaleString("ko-KR")}개사` +
    ` · 새 공시(N) ${nNew}건${nAll !== nNew ? ` (전체 ${nAll}건)` : ""}` +
    (rows.length > 1000 ? " (상위 1,000개 표시 — 검색·필터로 좁혀주세요)" : "");
}

function detail(r) {
  const c = E.companies[r.cc];
  const ps = E.periods.filter(p => c.d[p]); // 과거 → 최신 (최신이 오른쪽)
  const line = (lab, f) => `<tr><th class="l">${lab}</th>${ps.map(p => `<td>${f(c.d[p])}</td>`).join("")}</tr>`;
  const bal = Object.entries(INST).map(([k, n]) => `${n} ${fmt(r.bal[k])}`).join(" · ");
  const f = F[r.cc];
  const brw = f && f.items && !f.na
    ? `<div class="muted" style="margin-bottom:6px">차입금(${f.p}, ${f.fs === "CFS" ? "연결" : "별도"}, 억원): ${fmt(f.brw)}` +
      (f.items.length ? ` = ${f.items.map(([n, a]) => `${n} ${fmt(a)}`).join(" + ")}` : "") +
      ` · 차입금의존도 ${f.dep == null ? "–" : f.dep.toFixed(1) + "%"}</div>`
    : "";
  return `<tr class="detail"><td colspan="${COLS.length}">
    <div class="muted" style="margin-bottom:6px">${c.fs === "CFS" ? "연결" : "별도"} · 미상환 잔액(${r.balAsof || "–"}, 억원, 회사채는 공모): ${bal}</div>${brw}
    <table><thead><tr><th class="l"></th>${ps.map(p => c.d[p].rs ? `<th title="이후 보고서에서 회사가 재작성한 숫자">${p}*</th>` : `<th>${p}</th>`).join("")}</tr></thead><tbody>
      ${line(state.mode === "c" ? "매출(누적)" : "매출", v => fmt(pick(v, "rev")))}
      ${line(state.mode === "c" ? "영업이익(누적)" : "영업이익", v => fmt(pick(v, "op")))}
      ${line(state.mode === "c" ? "순이익(누적)" : "순이익", v => fmt(pick(v, "ni")))}
      ${line("자산총계", v => fmt(v.asset))}
      ${line("부채총계", v => fmt(v.liab))}
      ${line("자본총계", v => fmt(v.eq))}
      ${line("부채비율", v => v.eq > 0 ? (v.liab / v.eq * 100).toFixed(1) + "%" : "–")}
      <tr><th class="l">차입금의존도</th>${ps.map(p => {
        const d = f && f.h ? f.h[p] : null; // 분기별 (상세 재무제표 기준)
        return `<td>${d == null ? "–" : d.toFixed(1) + "%"}</td>`;
      }).join("")}</tr>
    </tbody></table></td></tr>`;
}

function bind() {
  $("#period").onchange = e => { state.period = e.target.value; build(); render(); };
  $("#mode").onclick = e => {
    const b = e.target.closest("button");
    if (!b) return;
    state.mode = b.dataset.v;
    $("#mode").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    build(); render();
  };
  $("#q").oninput = e => { state.q = e.target.value; render(); };
  $("#group").onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    state.group = b.dataset.v;
    $("#group").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    render();
  };
  $("#inst").onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    const v = b.dataset.v;
    state.inst.has(v) ? state.inst.delete(v) : state.inst.add(v);
    b.classList.toggle("on", state.inst.has(v));
    render();
  };
  $("#tbl thead").onclick = e => {
    const k = e.target.closest("th")?.dataset.k; if (!k) return;
    state.sort = state.sort.key === k ? { key: k, dir: -state.sort.dir } : { key: k, dir: COLS.find(c => c.key === k).l ? 1 : -1 };
    render();
  };
  $("#tbl tbody").onclick = e => {
    if (e.target.closest("a")) return; // 공시 링크 클릭은 펼치기 없이 이동
    const tr = e.target.closest("tr.row"); if (!tr) return;
    state.open = state.open === tr.dataset.cc ? null : tr.dataset.cc;
    render();
  };
}

// ───────── 발행사 리스트 탭 ─────────
const ICOLS = [
  { key: "cc", label: "기업코드", l: true },
  { key: "name", label: "기업명", l: true },
  { key: "mkt", label: "상장", l: true },
  { key: "asof", label: "최근 공시 기준", l: true },
  { key: "bond", label: "공모 회사채" },
  { key: "bpriv", label: "사모 회사채(참고)" }, // 사모사채·사모 CB/BW — 발행사 집계·총액에서 제외
  { key: "cp", label: "기업어음(CP)" },
  { key: "stb", label: "단기사채(전단채)" },
  { key: "cpstb", label: "CP+전단채" },
  { key: "total", label: "총" },
];
const ist = { sort: { key: "total", dir: -1 }, q: "", f: "all" };
let IROWS = [];

function buildIssuers() {
  IROWS = [];
  for (const [cc, u] of Object.entries(U.companies)) {
    const b = u.bal || {};
    const bond = b.bond || 0, cp = b.cp || 0, stb = b.stb || 0, bpriv = b.bond_priv || 0; // bond = 공모 회사채
    // 잔액 없는 기업도 모두 포함 (has: 잔액 > 0, notbl: 보고서에 잔액 표 없음)
    const has = bond > 0 || cp > 0 || stb > 0;
    const notbl = !u.bal || Object.values(u.bal).every(v => v == null);
    IROWS.push({ cc, name: u.name || cc, mkt: CLS[u.cls] || u.cls || "", asof: u.bal_asof || "", bond, bpriv, cp, stb, has, notbl,
                 cpstb: cp + stb, total: bond + cp + stb });
  }
}

function renderIssuers() {
  const { key, dir } = ist.sort;
  const q = ist.q.trim().toLowerCase();
  const rows = IROWS.filter(r => !q || r.name.toLowerCase().includes(q) || r.cc.includes(q))
    .filter(r => ist.f === "all" || (ist.f === "has" ? r.has : ist.f === "zero" ? !r.has && !r.notbl : r.notbl))
    .sort((a, b) => {
      const x = a[key], y = b[key];
      return (typeof x === "string" ? x.localeCompare(y, "ko") : x - y) * dir;
    });
  $("#itbl thead").innerHTML = "<tr>" + ICOLS.map(c =>
    `<th class="${c.l ? "l" : ""}" data-k="${c.key}">${c.label}${key === c.key ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`
  ).join("") + "</tr>";
  const num = v => v > 0 ? fmt(v) : "–";
  $("#itbl tbody").innerHTML = rows.map(r =>
    `<tr><td class="l">${r.cc}</td><td class="l">${r.name}</td><td class="l">${r.mkt}</td><td class="l">${r.asof || (r.notbl ? "잔액 표 없음" : "–")}</td>` +
    ["bond", "bpriv", "cp", "stb", "cpstb", "total"].map(k => `<td>${num(r[k])}</td>`).join("") + "</tr>"
  ).join("");
  const sum = k => rows.reduce((s, r) => s + r[k], 0);
  let tf = $("#itbl tfoot");
  if (!tf) { tf = document.createElement("tfoot"); $("#itbl").appendChild(tf); }
  tf.innerHTML = `<tr><td class="l" colspan="4">합계 (${rows.length.toLocaleString("ko-KR")}개사)</td>` +
    ["bond", "bpriv", "cp", "stb", "cpstb", "total"].map(k => `<td>${fmt(sum(k))}</td>`).join("") + "</tr>";
  const n = v => v.toLocaleString("ko-KR");
  const nHas = IROWS.filter(r => r.has).length, nTbl = IROWS.filter(r => r.notbl).length;
  $("#ifilt [data-v=notbl]").hidden = !nTbl;
  $("#istatus").textContent = `표시 ${n(rows.length)}개사 · 전체 ${n(IROWS.length)} = 잔액 있음 ${n(nHas)} + 잔액 0 ${n(IROWS.length - nHas - nTbl)}${nTbl ? ` + 잔액 표 없음 ${n(nTbl)}` : ""} · 목록 갱신 ${U.updated}`;
}

function bindIssuers() {
  $("#iq").oninput = e => { ist.q = e.target.value; renderIssuers(); };
  $("#ifilt").onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    ist.f = b.dataset.v;
    $("#ifilt").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    renderIssuers();
  };
  $("#itbl thead").onclick = e => {
    const k = e.target.closest("th")?.dataset.k; if (!k) return;
    ist.sort = ist.sort.key === k ? { key: k, dir: -ist.sort.dir }
      : { key: k, dir: ICOLS.find(c => c.key === k).l ? 1 : -1 };
    renderIssuers();
  };
}

// ───────── 탭 전환 ─────────
function showTab(t) {
  $("#tabs").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  $("#tab-earn").hidden = t !== "earn";
  $("#tab-iss").hidden = t !== "iss";
  try { location.hash = t; } catch (_) {}
}
$("#tabs").onclick = e => { const b = e.target.closest("button"); if (b) showTab(b.dataset.tab); };
const tabFromHash = () => showTab(location.hash === "#iss" ? "iss" : "earn");
window.addEventListener("hashchange", tabFromHash);
tabFromHash();

// ───────── 데이터 로드 (탭별로 따로: 한쪽이 없어도 다른 쪽은 표시) ─────────
const getJSON = u => fetch(u, { cache: "no-store" }).then(r => r.ok ? r.json() : Promise.reject(u));
const pU = getJSON("data/universe.json");
pU.then(u => { U = u; bindIssuers(); buildIssuers(); renderIssuers(); })
  .catch(() => { $("#istatus").textContent = "아직 발행사 목록이 없어요. (데이터 수집 중)"; });

const pF = getJSON("data/fs_index.json").then(f => f.companies).catch(() => ({})); // 없으면 빈칸
Promise.all([pU, getJSON("data/earnings.json"), pF])
  .then(([u, e, f]) => {
    U = u; E = e; F = f; NEW_FROM = newFrom(E.updated);
    // 데이터가 있는 분기만, 최신이 기본
    const ps = E.periods.filter(p => Object.values(E.companies).some(c => c.d[p]));
    $("#period").innerHTML = ps.slice().reverse().map(p => `<option>${p}</option>`).join("");
    state.period = ps[ps.length - 1];
    $("#updated").textContent = `· 마지막 수집 ${E.updated_at || E.updated} (평일 08·13·19시경 자동)`;
    bind(); build(); render();
  })
  .catch(() => { $("#status").textContent = "아직 수집된 데이터가 없어요. (Actions 에서 데이터 수집을 먼저 실행하세요)"; });
