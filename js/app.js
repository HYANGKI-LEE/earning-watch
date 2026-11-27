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

// ───────── 그룹 실적 탭 (공정위 기업집단, 계열사 별도 합산) ─────────
let S = null, GROWS = [];
const gst = { period: null, mode: "q", fin: "nf", q: "", sort: { key: "rank", dir: 1 }, open: null };
const gpick = (v, k) => v == null ? null : (gst.mode === "c" ? v["c" + k] : v[k]) ?? null;
const inFin = fin => gst.fin === "all" || (gst.fin === "f" ? !!fin : !fin);
const gname = cc => (U && U.companies[cc] && U.companies[cc].name) || cc;
const FLOWS = ["rev", "op", "ni"];

// 회사 목록 ms([기업코드, 금융]) 의 기간 p 별도 합산. YoY 는 올해·전년 둘 다 있는 회사끼리만
function agg(ms, p) {
  const py = prevYear(p), o = { n: 0, asset: null, liab: null, eq: null };
  const cur = {}, prv = {}, cnt = {};
  for (const k of FLOWS) { o[k] = null; cur[k] = 0; prv[k] = 0; cnt[k] = 0; }
  for (const [cc] of ms) {
    const c = S.companies[cc]; if (!c) continue;
    const v = c.d[p]; if (!v || !v.rno) continue; // 이 분기 보고서가 있는 회사만
    const y = c.d[py];
    o.n++;
    for (const k of FLOWS) {
      const a = gpick(v, k); if (a == null) continue;
      o[k] = (o[k] || 0) + a;
      const b = gpick(y, k);
      if (b != null) { cur[k] += a; prv[k] += b; cnt[k]++; }
    }
    for (const k of ["asset", "liab", "eq"]) if (v[k] != null) o[k] = (o[k] || 0) + v[k];
  }
  for (const k of FLOWS) {
    o[k + "Y"] = cnt[k] ? growth(cur[k], prv[k]) : null;
    o[k + "T"] = cnt[k] && k !== "rev" ? turn(cur[k], prv[k]) : null;
  }
  o.opm = o.rev && o.op != null ? o.op / o.rev * 100 : null;
  o.debt = o.eq > 0 ? o.liab / o.eq * 100 : null;
  return o;
}

const GCOLS = [
  { key: "rank", label: "순위", l: true },
  { key: "name", label: "그룹", l: true },
  { key: "n", label: "집계" },
  { key: "rev", label: "매출" },
  { key: "revY", label: "YoY", g: true },
  { key: "op", label: "영업이익" },
  { key: "opY", label: "YoY", g: true, t: "opT" },
  { key: "opm", label: "영업이익률", r: true },
  { key: "ni", label: "순이익" },
  { key: "niY", label: "YoY", g: true, t: "niT" },
  { key: "asset", label: "자산총계" },
  { key: "debt", label: "부채비율", r: true },
];

function buildGroups() {
  // 순위: 공정위 소속회사 자산총액(금융보험업 제외) 순 — 공정위 공식 순위(금융사는 자본총계로 계산)와 거의 같음
  const order = Object.entries(S.groups).sort((a, b) => (b[1].nf ?? b[1].a) - (a[1].nf ?? a[1].a));
  GROWS = order.map(([g, G], i) => {
    const ms = G.m.filter(x => inFin(x[1]));
    return { g, name: g, rank: i + 1, tot: G.n, ms, ...agg(ms, gst.period) };
  }).filter(r => r.ms.length); // 이 범위(비금융/금융)에 DART 회사가 없는 그룹은 숨김
}

const gy = (v, t) => t ? `<td class="${t === "흑전" ? "up" : "down"}">${t}</td>` : `<td class="${cls(v)}">${pct(v)}</td>`;
const rpct = v => v == null ? "–" : v.toFixed(1) + "%";

function renderGroups() {
  const { key, dir } = gst.sort;
  const q = gst.q.trim().toLowerCase();
  const rows = GROWS.filter(r => !q || r.name.toLowerCase().includes(q) || r.ms.some(([cc]) => gname(cc).toLowerCase().includes(q)))
    .sort((a, b) => {
      const x = a[key], y = b[key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (typeof x === "string" ? x.localeCompare(y, "ko") : x - y) * dir;
    });
  $("#gtbl thead").innerHTML = "<tr>" + GCOLS.map(c =>
    `<th class="${c.l ? "l" : ""}" data-k="${c.key}">${c.label}${key === c.key ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("") + "</tr>";
  const html = [];
  for (const r of rows) {
    html.push(`<tr class="row" data-g="${r.g}">` + GCOLS.map(c => {
      if (c.key === "rank") return `<td class="l">${r.rank}</td>`;
      if (c.key === "name") return `<td class="l">${r.name}</td>`;
      if (c.key === "n") return `<td title="이 분기 실적이 있는 회사 / DART에서 찾은 소속회사 (공정위 전체 ${r.tot}개)">${r.n} / ${r.ms.length}</td>`;
      if (c.g) return gy(r[c.key], c.t && r[c.t]);
      if (c.r) return `<td>${rpct(r[c.key])}</td>`;
      return `<td>${fmt(r[c.key])}</td>`;
    }).join("") + "</tr>");
    if (gst.open === r.g) html.push(gdetail(r));
  }
  $("#gtbl tbody").innerHTML = html.join("");
  const has = rows.filter(r => r.n).length;
  $("#gstatus").textContent = `${gst.period}${gst.mode === "c" ? " 누적" : ""} · ${rows.length}개 그룹 (실적 있는 그룹 ${has}) · ` +
    `${{ nf: "비금융 계열사", all: "금융 포함 전체 계열사", f: "금융 계열사만" }[gst.fin]} 별도 합산 · 그룹을 누르면 분기 추이와 계열사별 실적`;
}

function gdetail(r) {
  const ps = S.periods, G = S.groups[r.g];
  const parts = [["비금융", r.ms.filter(x => !x[1])], ["금융", r.ms.filter(x => x[1])]].filter(([, m]) => m.length);
  const series = parts.length > 1 ? [["합계", r.ms], ...parts] : [["합계", r.ms]];
  const LAB = { rev: "매출", op: "영업이익", ni: "순이익" };
  const yo = (o, k) => {
    const t = o[k + "T"];
    if (t) return `<small class="${t === "흑전" ? "up" : "down"}">${t}</small>`;
    return o[k + "Y"] == null ? "" : `<small class="${cls(o[k + "Y"])}">${pct(o[k + "Y"])}</small>`;
  };
  const trend = series.map(([lab, m]) => {
    const by = Object.fromEntries(ps.map(p => [p, agg(m, p)]));
    return FLOWS.map(k => `<tr><th class="l">${lab} ${LAB[k]}${gst.mode === "c" ? "(누적)" : ""}</th>` +
      ps.map(p => `<td>${by[p].n ? fmt(by[p][k]) + " " + yo(by[p], k) : "–"}</td>`).join("") + "</tr>").join("") +
      `<tr><th class="l">${lab} 부채비율</th>${ps.map(p => `<td>${rpct(by[p].debt)}</td>`).join("")}</tr>` +
      `<tr><th class="l">${lab} 집계 회사</th>${ps.map(p => `<td>${by[p].n}</td>`).join("")}</tr>`;
  }).join("");

  // 선택 분기 계열사별 (실적 있는 회사 먼저, 매출 큰 순)
  const p = gst.period, py = prevYear(p);
  const mem = r.ms.map(([cc, fin]) => {
    const c = S.companies[cc], v = c && c.d[p], y = c && c.d[py];
    const ok = !!(v && v.rno);
    const o = { cc, fin, ok, name: gname(cc), cls: (U && U.companies[cc] && U.companies[cc].cls) || "E" };
    if (ok) {
      for (const k of FLOWS) { o[k] = gpick(v, k); o[k + "Y"] = growth(o[k], gpick(y, k)); o[k + "T"] = k === "rev" ? null : turn(o[k], gpick(y, k)); }
      o.debt = v.eq > 0 ? v.liab / v.eq * 100 : null; o.dt = v.dt; o.rno = v.rno;
    }
    return o;
  }).sort((a, b) => (b.ok - a.ok) || ((b.rev ?? -Infinity) - (a.rev ?? -Infinity)));
  const memRows = mem.map(m => `<tr${m.ok ? "" : ' class="muted"'}><td class="l">${m.name}${m.fin ? ' <span class="badge">금융</span>' : ""}</td>` +
    `<td class="l">${CLS[m.cls] || m.cls}</td>` +
    (m.ok ? FLOWS.map(k => `<td>${fmt(m[k])}</td>${gy(m[k + "Y"], m[k + "T"])}`).join("") +
      `<td>${rpct(m.debt)}</td><td><a class="dartlink" href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${m.rno}" target="_blank" rel="noopener">${fmtDt(m.dt)}</a></td>`
      : `<td colspan="8" class="l">${p} 실적 없음 (아직 미공시 또는 DART 재무 데이터 없음)</td>`) + "</tr>").join("");
  const off = G.n - G.m.length;
  return `<tr class="detail"><td colspan="${GCOLS.length}">
    <div class="muted" style="margin-bottom:6px">${r.g} · 공정위 소속회사 ${G.n}개 중 DART에서 찾은 ${G.m.length}개${off ? ` (나머지 ${off}개는 DART 정기공시 대상 아님 — 소규모 비상장·해외법인 등)` : ""} · 별도 합산, 억원</div>
    <table><thead><tr><th class="l"></th>${ps.map(p => `<th>${p}</th>`).join("")}</tr></thead><tbody>${trend}</tbody></table>
    <div class="muted" style="margin:10px 0 6px">${p}${gst.mode === "c" ? " 누적" : ""} 계열사별 (별도)</div>
    <table><thead><tr><th class="l">회사</th><th class="l">상장</th><th>매출</th><th>YoY</th><th>영업이익</th><th>YoY</th><th>순이익</th><th>YoY</th><th>부채비율</th><th>공시일</th></tr></thead>
    <tbody>${memRows}</tbody></table></td></tr>`;
}

function bindGroups() {
  $("#gperiod").onchange = e => { gst.period = e.target.value; buildGroups(); renderGroups(); };
  const chips = (sel, f) => $(sel).onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    $(sel).querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    f(b.dataset.v); buildGroups(); renderGroups();
  };
  chips("#gmode", v => gst.mode = v);
  chips("#gfin", v => gst.fin = v);
  $("#gq").oninput = e => { gst.q = e.target.value; renderGroups(); };
  $("#gtbl thead").onclick = e => {
    const k = e.target.closest("th")?.dataset.k; if (!k) return;
    gst.sort = gst.sort.key === k ? { key: k, dir: -gst.sort.dir } : { key: k, dir: GCOLS.find(c => c.key === k).l ? 1 : -1 };
    renderGroups();
  };
  $("#gtbl tbody").onclick = e => {
    if (e.target.closest("a")) return;
    const tr = e.target.closest("tr.row"); if (!tr) return;
    gst.open = gst.open === tr.dataset.g ? null : tr.dataset.g;
    renderGroups();
  };
}

// ───────── 탭 전환 ─────────
function showTab(t) {
  $("#tabs").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  $("#tab-earn").hidden = t !== "earn";
  $("#tab-iss").hidden = t !== "iss";
  $("#tab-grp").hidden = t !== "grp";
  try { location.hash = t; } catch (_) {}
}
$("#tabs").onclick = e => { const b = e.target.closest("button"); if (b) showTab(b.dataset.tab); };
const tabFromHash = () => showTab(["#iss", "#grp"].includes(location.hash) ? location.hash.slice(1) : "earn");
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

Promise.all([pU.catch(() => null), getJSON("data/earnings_sep.json")])
  .then(([u, s]) => {
    if (!s.groups) throw 0;
    U = U || u; S = s;
    for (const cc in S.companies) S.companies[cc] = { d: S.companies[cc] }; // 별도 파일은 {기업코드: 기간별 값} → 연결 파일과 같은 모양으로
    const ps = S.periods.filter(p => Object.values(S.companies).some(c => c.d[p] && c.d[p].rno));
    $("#gperiod").innerHTML = ps.slice().reverse().map(p => `<option>${p}</option>`).join("");
    gst.period = ps[ps.length - 1];
    const a = S.groups_asof || "";
    $("#gasof").textContent = a ? `(${a.slice(0, 4)}.${a.slice(4)} 기준)` : "";
    bindGroups(); buildGroups(); renderGroups();
  })
  .catch(() => { $("#gstatus").textContent = "아직 그룹 실적 데이터가 없어요."; });
