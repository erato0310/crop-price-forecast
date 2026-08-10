/* 전북 농산물 가격예측 지도 — 프런트엔드
   서버 없음: data/app_data.json(사전 계산된 예측) + data/jeonbuk_geo.json(시군 경계)만 읽는다.
   지도·차트 모두 외부 라이브러리 없이 SVG를 직접 그린다. */

const FMT = new Intl.NumberFormat("ko-KR");
const CHART = { w: 1000, h: 340, ml: 62, mr: 16, mt: 14, mb: 30 };
const RAMP = ["--ramp-0", "--ramp-1", "--ramp-2", "--ramp-3", "--ramp-4", "--ramp-5"];

let DATA = null, GEO = null;
let state = {
  mode: "crop",
  crop: null,
  county: null,
  start: null,          // 월 인덱스(y*12 + m-1)
  end: null,
  detail: null,         // {crop, county}
  sort: { key: "avg", dir: "desc" },
};
let rows = [];          // 현재 화면의 결과 행

/* ── 유틸 ─────────────────────────────────────── */
const $ = (id) => document.getElementById(id);
const won = (v) => FMT.format(Math.round(v));
const miOf = (ym) => { const [y, m] = ym.split("-").map(Number); return y * 12 + (m - 1); };
const ymOf = (mi) => `${Math.floor(mi / 12)}-${String((mi % 12) + 1).padStart(2, "0")}`;
const ymKo = (mi) => `${Math.floor(mi / 12)}년 ${(mi % 12) + 1}월`;
const cropName = (id) => (DATA.crops.find((c) => c.id === id) || {}).name || id;
const countyName = (id) => (GEO.counties[id] || {}).name || id;
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

/* ── 기간 집계 ─────────────────────────────────
   선택 기간에 걸친 달만 골라 최저/최고/평균을 낸다.
   실측과 예측이 섞일 수 있으므로 각각 몇 달인지도 같이 돌려준다. */
function aggregate(cropId, countyId, s, e) {
  const c = DATA.combos[`${cropId}|${countyId}`];
  if (!c) return null;

  let min = Infinity, max = -Infinity, sum = 0, n = 0, nA = 0, nF = 0;
  let spikeMax = 0;
  const take = (mi, price, isFc, spike) => {
    if (mi < s || mi > e) return;
    min = Math.min(min, price); max = Math.max(max, price);
    sum += price; n++;
    if (isFc) { nF++; if (spike > spikeMax) spikeMax = spike; } else nA++;
  };
  for (const d of c.hist) take(miOf(d[0]), d[1], false, 0);
  for (const d of c.fc) take(miOf(d[0]), d[1], true, d[4]);
  if (!n) return null;

  const lastActualMi = miOf(c.hist[c.hist.length - 1][0]);
  return {
    cropId, countyId, min, max, avg: sum / n, n, nActual: nA, nForecast: nF,
    spikeMax, cvMape: c.cv_mape,
    stale: lastActualMi < miOf(DATA.meta.last_actual_ym),
    lastActualMi, src: c.src,
  };
}

function kindOf(r) {
  if (r.nForecast === 0) return { cls: "actual", label: "실측" };
  if (r.nActual === 0) return { cls: "forecast", label: "예측" };
  return { cls: "mixed", label: `실측 ${r.nActual} + 예측 ${r.nForecast}` };
}

/* ── 초기화 ───────────────────────────────────── */
async function init() {
  const [a, g] = await Promise.all([
    fetch("data/app_data.json").then((r) => r.json()),
    fetch("data/jeonbuk_geo.json").then((r) => r.json()),
  ]);
  DATA = a; GEO = g;

  $("updated").textContent =
    `${DATA.meta.last_actual_ym.replace("-", "년 ")}월 거래 기준 · ${DATA.meta.n_combos}개 조합`;

  state.crop = DATA.crops[0].id;
  state.county = DATA.counties[0].id;

  buildSelects();
  applyPreset("next6");
  bindEvents();
  render();
}

function buildSelects() {
  $("cropSel").innerHTML = DATA.crops.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
  $("cropSel").value = state.crop;
  $("countySel").innerHTML = DATA.counties
    .map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
  $("countySel").value = state.county;

  // 데이터가 실제로 존재하는 전체 구간만 고르게 한다
  const allMi = [];
  for (const c of Object.values(DATA.combos)) {
    if (c.hist.length) allMi.push(miOf(c.hist[0][0]));
    if (c.fc.length) allMi.push(miOf(c.fc[c.fc.length - 1][0]));
  }
  state.minMi = Math.min(...allMi);
  state.maxMi = Math.max(...allMi);

  const y0 = Math.floor(state.minMi / 12), y1 = Math.floor(state.maxMi / 12);
  const years = [];
  for (let y = y0; y <= y1; y++) years.push(`<option value="${y}">${y}년</option>`);
  const months = [];
  for (let m = 1; m <= 12; m++) months.push(`<option value="${m}">${m}월</option>`);
  ["startY", "endY"].forEach((id) => ($(id).innerHTML = years.join("")));
  ["startM", "endM"].forEach((id) => ($(id).innerHTML = months.join("")));
}

function applyPreset(name) {
  const last = miOf(DATA.meta.last_actual_ym);
  if (name === "next6") { state.start = last + 1; state.end = last + 6; }
  else if (name === "next12") { state.start = last + 1; state.end = last + 12; }
  else { state.start = last - 11; state.end = last; }
  state.start = Math.max(state.minMi, state.start);
  state.end = Math.min(state.maxMi, state.end);
  syncYmSelects();
}

function syncYmSelects() {
  $("startY").value = Math.floor(state.start / 12);
  $("startM").value = (state.start % 12) + 1;
  $("endY").value = Math.floor(state.end / 12);
  $("endM").value = (state.end % 12) + 1;
}

function readYmSelects() {
  let s = Number($("startY").value) * 12 + (Number($("startM").value) - 1);
  let e = Number($("endY").value) * 12 + (Number($("endM").value) - 1);
  if (s > e) e = s;                                    // 뒤집힌 입력은 조용히 바로잡는다
  state.start = Math.max(state.minMi, Math.min(state.maxMi, s));
  state.end = Math.max(state.minMi, Math.min(state.maxMi, e));
  syncYmSelects();
}

function bindEvents() {
  $("modeGroup").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    state.mode = b.dataset.mode;
    [...ev.currentTarget.children].forEach((x) =>
      x.setAttribute("aria-checked", String(x === b)));
    $("cropField").hidden = state.mode !== "crop";
    $("countyField").hidden = state.mode !== "county";
    state.detail = null;
    state.sort = { key: "avg", dir: "desc" };
    render();
  });

  $("cropSel").addEventListener("change", (e) => { state.crop = e.target.value; state.detail = null; render(); });
  $("countySel").addEventListener("change", (e) => { state.county = e.target.value; state.detail = null; render(); });

  ["startY", "startM", "endY", "endM"].forEach((id) =>
    $(id).addEventListener("change", () => { readYmSelects(); render(); }));

  $("presetGroup").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    applyPreset(b.dataset.preset); render();
  });

  $("detailClose").addEventListener("click", () => { state.detail = null; render(); });

  $("themeToggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
    render();
  });
}

/* ── 렌더 ─────────────────────────────────────── */
function render() {
  rows = computeRows();
  renderRangeNote();
  renderNotice();
  renderMap();
  renderTable();
  renderDetail();
}

function computeRows() {
  const out = [];
  if (state.mode === "crop") {
    for (const c of DATA.counties) {
      const r = aggregate(state.crop, c.id, state.start, state.end);
      if (r) out.push({ ...r, label: c.name, key: c.id });
    }
  } else {
    for (const c of DATA.crops) {
      const r = aggregate(c.id, state.county, state.start, state.end);
      if (r) out.push({ ...r, label: c.name, key: c.id });
    }
  }
  const { key, dir } = state.sort;
  out.sort((a, b) => {
    const va = key === "label" ? a.label : a[key];
    const vb = key === "label" ? b.label : b[key];
    const c = key === "label" ? String(va).localeCompare(vb, "ko") : va - vb;
    return dir === "asc" ? c : -c;
  });
  return out;
}

function renderRangeNote() {
  const months = state.end - state.start + 1;
  const subject = state.mode === "crop"
    ? `<b>${cropName(state.crop)}</b>` : `<b>${countyName(state.county)}</b>`;
  const target = state.mode === "crop"
    ? `시군 ${rows.length}곳` : `작물 ${rows.length}종`;
  $("rangeNote").innerHTML =
    `${subject} · <b>${ymKo(state.start)} ~ ${ymKo(state.end)}</b> (${months}개월) · ${target} 집계`;
}

function renderNotice() {
  const el = $("notice");
  const msgs = [];
  const stale = rows.filter((r) => r.stale);
  const gpj = rows.filter((r) => r.src === "gpj");
  const far = state.end - miOf(DATA.meta.last_actual_ym);

  if (stale.length) {
    msgs.push(`<div><strong>최근 거래 기록이 없는 ${state.mode === "crop" ? "시군" : "작물"}이 ` +
      `${stale.length}곳 있습니다.</strong> ` +
      `${stale.slice(0, 4).map((r) => `${r.label}(${ymKo(r.lastActualMi)}까지)`).join(", ")}` +
      `${stale.length > 4 ? " 외" : ""} — 이후 예측은 실제 시세를 반영하지 못할 수 있습니다.</div>`);
  }
  if (gpj.length) {
    msgs.push(`<div><strong>산지공판장 정산가격을 쓴 항목이 있습니다</strong> ` +
      `(${gpj.map((r) => r.label).join(", ")}). 도매시장 표본이 부족한 경우로, ` +
      `가격 수준이 다른 항목과 직접 비교되지 않습니다.</div>`);
  }
  if (far > 12) {
    msgs.push(`<div><strong>마지막 실측에서 1년 넘게 떨어진 기간이 포함돼 있습니다.</strong> ` +
      `그 구간의 예측은 불확실성이 매우 큽니다 — 방향성 참고용으로만 보세요.</div>`);
  }
  el.innerHTML = msgs.join("");
  el.classList.toggle("show", msgs.length > 0);
}

/* ── 지도 ─────────────────────────────────────── */
/* 색 척도는 도매시장(origin) 기준 행으로만 만든다.
   산지공판장(gpj) 정산가는 거래 단위가 달라 도매시장 가격과 같은 축에 놓을 수 없다 —
   한 척도에 섞으면 "저 시군이 제일 싸다"는 틀린 인상을 준다. gpj는 빗금으로 따로 표시. */
function colorScale() {
  const colors = RAMP.map(cssVar);
  const vals = rows.filter((r) => r.src === "origin").map((r) => r.avg);
  if (!vals.length) {
    return { colorOf: () => cssVar("--ramp-none"), lo: 0, hi: 0, colors, empty: true };
  }
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const colorOf = (v) => {
    if (v == null) return cssVar("--ramp-none");
    if (hi === lo) return colors[Math.floor(colors.length / 2)];
    const t = (v - lo) / (hi - lo);
    return colors[Math.min(colors.length - 1, Math.floor(t * colors.length))];
  };
  return { colorOf, lo, hi, colors, empty: false };
}

function renderMap() {
  const svg = $("map");
  const scale = colorScale();
  const parts = [
    // gpj(공판장 기준) 시군 표시용 빗금 — 색이 아니라 무늬로 구분해 색맹·흑백 인쇄에서도 읽힌다
    `<defs><pattern id="gpjHatch" width="7" height="7" patternTransform="rotate(45)"
        patternUnits="userSpaceOnUse">
        <rect width="7" height="7" fill="${cssVar("--ramp-none")}"/>
        <line x1="0" y1="0" x2="0" y2="7" stroke="${cssVar("--text-muted")}" stroke-width="2.6"/>
      </pattern></defs>`,
  ];

  for (const [cid, geo] of Object.entries(GEO.counties)) {
    let fill, selected = false, r = null, noData = false;
    if (state.mode === "crop") {
      r = rows.find((x) => x.key === cid) || null;
      noData = !r;
      // 데이터 없음은 램프의 어느 끝과도 닮지 않게 '빈 면'으로 둔다.
      // (다크모드에서 회색 채움은 램프의 최저값 색과 구별이 잘 안 됐다)
      fill = !r ? cssVar("--plane")
           : r.src === "gpj" ? "url(#gpjHatch)"
           : scale.colorOf(r.avg);
      selected = state.detail && state.detail.county === cid;
    } else {
      selected = cid === state.county;
      fill = selected ? cssVar("--series-1") : cssVar("--ramp-none");
    }
    const title = state.mode === "crop"
      ? (r ? `${geo.name} 평균 ${won(r.avg)}원${r.src === "gpj" ? " (공판장 기준 — 다른 시군과 비교 불가)" : ""}`
           : `${geo.name} 데이터 없음`)
      : geo.name;
    parts.push(
      `<path class="county${selected ? " selected" : ""}${noData ? " nodata" : ""}" d="${geo.d}"
         fill="${fill}" data-county="${cid}" tabindex="0" role="button"
         aria-label="${title}"><title>${title}</title></path>`);
  }

  // 라벨은 도형 위에 한 번에 얹는다(경계선에 가리지 않게).
  // geo.room = 라벨 자리에서 경계까지의 여유. 좁은 시군(전주시)에 값까지 넣으면
  // 옆 시군을 침범해서 오히려 오독을 부르므로 이름만 남기고 값은 뺀다(표·툴팁에는 그대로 있음).
  const ROOM_FOR_VALUE = 26;
  for (const [cid, geo] of Object.entries(GEO.counties)) {
    const r = state.mode === "crop" ? rows.find((x) => x.key === cid) : null;
    const roomy = (geo.room ?? 99) >= ROOM_FOR_VALUE;
    const showValue = !!r && roomy;
    const small = !roomy ? ' style="font-size:11px"' : "";
    parts.push(`<text class="clabel" x="${geo.cx}" y="${geo.cy + (showValue ? -4 : 0)}"
      text-anchor="middle"${small}>${geo.name}</text>`);
    if (showValue) {
      parts.push(`<text class="cvalue" x="${geo.cx}" y="${geo.cy + 11}" text-anchor="middle">${won(r.avg)}</text>`);
    }
  }

  svg.setAttribute("viewBox", GEO.viewBox);
  svg.innerHTML = parts.join("");

  svg.querySelectorAll(".county").forEach((el) => {
    const cid = el.dataset.county;
    const open = () => {
      if (state.mode === "crop") {
        if (DATA.combos[`${state.crop}|${cid}`]) state.detail = { crop: state.crop, county: cid };
      } else {
        state.county = cid; $("countySel").value = cid; state.detail = null;
      }
      render();
    };
    el.addEventListener("click", open);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  });

  $("mapTitle").textContent = state.mode === "crop"
    ? `${cropName(state.crop)} — 시군별 평균 가격`
    : `${countyName(state.county)} 선택`;
  $("mapDesc").textContent = state.mode === "crop"
    ? `${ymKo(state.start)} ~ ${ymKo(state.end)}의 평균 가격입니다. 색이 진할수록 비쌉니다.`
    : `지도에서 시군을 눌러 바꿀 수 있습니다. 오른쪽 표에 작물별 가격이 나옵니다.`;

  renderLegend(scale);
}

function renderLegend(scale) {
  const el = $("legendScale");
  if (state.mode !== "crop" || !rows.length) { el.innerHTML = ""; return; }
  const steps = scale.colors.map((c) => `<span class="step" style="background:${c}"></span>`).join("");
  const missing = DATA.counties.length - rows.length;
  const nGpj = rows.filter((r) => r.src === "gpj").length;
  el.innerHTML =
    (scale.empty ? "" :
      `<span class="cap">${won(scale.lo)}원</span><span class="steps">${steps}</span>` +
      `<span class="cap">${won(scale.hi)}원</span>`) +
    (nGpj > 0
      ? `<span class="none-key"><span class="none-swatch hatch"></span>공판장 기준 ${nGpj}곳 (비교 불가)</span>` : "") +
    (missing > 0
      ? `<span class="none-key"><span class="none-swatch"></span>데이터 없음 ${missing}곳</span>` : "");
}

/* ── 결과표 ───────────────────────────────────── */
function renderTable() {
  const first = state.mode === "crop" ? "시군" : "작물";
  const cols = [
    ["label", first], ["min", "최저"], ["avg", "평균"], ["max", "최고"], ["kind", "자료"],
  ];
  $("summaryHead").innerHTML = cols.map(([k, t]) => {
    const sorted = state.sort.key === k;
    const aria = sorted ? ` aria-sort="${state.sort.dir === "asc" ? "ascending" : "descending"}"` : "";
    return `<th scope="col" data-key="${k}"${aria}>${t}</th>`;
  }).join("");

  const scale = colorScale();
  if (!rows.length) {
    $("summaryBody").innerHTML =
      `<tr><td class="empty-row" colspan="5">선택한 기간에 데이터가 있는 조합이 없습니다. 기간을 넓혀 보세요.</td></tr>`;
  } else {
    $("summaryBody").innerHTML = rows.map((r) => {
      const k = kindOf(r);
      const sel = state.detail &&
        ((state.mode === "crop" && state.detail.county === r.key) ||
         (state.mode === "county" && state.detail.crop === r.key));
      const sw = state.mode === "crop"
        ? `<span class="swatch-cell" style="background:${scale.colorOf(r.avg)}"></span>` : "";
      return `<tr data-key="${r.key}" class="${sel ? "selected" : ""}">
        <td>${sw}${r.label}${r.stale ? ' <span class="pill mixed">자료 오래됨</span>' : ""}</td>
        <td>${won(r.min)}</td><td>${won(r.avg)}</td><td>${won(r.max)}</td>
        <td><span class="pill ${k.cls}">${k.label}</span></td>
      </tr>`;
    }).join("");
  }

  $("summaryHead").querySelectorAll("th").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.dataset.key;
      if (k === "kind") return;
      state.sort = state.sort.key === k
        ? { key: k, dir: state.sort.dir === "asc" ? "desc" : "asc" }
        : { key: k, dir: k === "label" ? "asc" : "desc" };
      render();
    });
  });
  $("summaryBody").querySelectorAll("tr[data-key]").forEach((tr) => {
    tr.addEventListener("click", () => {
      state.detail = state.mode === "crop"
        ? { crop: state.crop, county: tr.dataset.key }
        : { crop: tr.dataset.key, county: state.county };
      render();
      $("detailCard").scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });

  $("tableTitle").textContent = state.mode === "crop"
    ? "시군별 가격 요약" : `${countyName(state.county)}의 작물별 가격 요약`;
}

/* ── 상세 추이 ────────────────────────────────── */
function renderDetail() {
  const card = $("detailCard");
  if (!state.detail) { card.hidden = true; return; }
  const { crop, county } = state.detail;
  const c = DATA.combos[`${crop}|${county}`];
  if (!c) { card.hidden = true; return; }
  card.hidden = false;

  const agg = aggregate(crop, county, state.start, state.end);
  $("detailTitle").textContent = `${countyName(county)} ${cropName(crop)} — 월별 상세`;
  $("detailDesc").innerHTML = agg
    ? `선택 기간(${ymKo(state.start)}~${ymKo(state.end)}) 최저 <b>${won(agg.min)}</b> · ` +
      `평균 <b>${won(agg.avg)}</b> · 최고 <b>${won(agg.max)}</b>원` +
      (agg.nForecast ? ` · 기간 내 최고 폭등확률 ${(agg.spikeMax * 100).toFixed(0)}%` : "")
    : "선택 기간에는 이 조합의 데이터가 없습니다.";

  drawChart(c);
  drawAccuracy(c);
}

function pathWithGaps(points) {
  let d = "", prev = null;
  for (const p of points) {
    d += (prev !== null && p.mi === prev + 1 ? "L" : "M") + `${p.sx.toFixed(1)},${p.sy.toFixed(1)}`;
    prev = p.mi;
  }
  return d;
}

let chartPoints = [];

function drawChart(c) {
  const svg = $("chart");
  const { w, h, ml, mr, mt, mb } = CHART;
  const plotW = w - ml - mr, plotH = h - mt - mb;

  // 선택 기간이 보이도록 앞뒤로 여유를 두고 자른다
  const pad = 6;
  const lo = Math.min(state.start - pad, miOf(DATA.meta.last_actual_ym) - 12);
  const hiM = Math.max(state.end + pad, state.start + 12);
  const hist = c.hist.filter((d) => miOf(d[0]) >= lo && miOf(d[0]) <= hiM);
  const fc = c.fc.filter((d) => miOf(d[0]) >= lo && miOf(d[0]) <= hiM);
  if (!hist.length && !fc.length) { svg.innerHTML = ""; return; }

  const mi0 = hist.length ? miOf(hist[0][0]) : miOf(fc[0][0]);
  const mi1 = fc.length ? miOf(fc[fc.length - 1][0]) : miOf(hist[hist.length - 1][0]);
  const span = Math.max(1, mi1 - mi0);
  const x = (mi) => ml + ((mi - mi0) / span) * plotW;

  // 먼 미래의 구간까지 y축에 넣으면 실제 변동이 눌린다 — 앞 6개월 구간만 반영하고 넘치면 clip
  const band = fc.slice(0, 6);
  const vals = [...hist.map((d) => d[1]), ...fc.map((d) => d[1]),
                ...band.map((d) => d[2]), ...band.map((d) => d[3])];
  let ylo = Math.min(...vals), yhi = Math.max(...vals);
  const p = (yhi - ylo) * 0.10 || yhi * 0.1;
  ylo = Math.max(0, ylo - p); yhi += p;
  const y = (v) => mt + plotH - ((v - ylo) / (yhi - ylo)) * plotH;
  const yc = (v) => Math.max(mt - 2, Math.min(mt + plotH + 2, y(v)));

  const parts = [`<defs><clipPath id="pc"><rect x="${ml}" y="${mt}" width="${plotW}" height="${plotH}"/></clipPath></defs>`];

  // 선택 기간 음영 — 표에 나온 숫자가 어느 구간인지 한눈에 맞춰 보이게
  const sx = x(Math.max(mi0, state.start)), ex = x(Math.min(mi1, state.end));
  if (ex > sx) {
    parts.push(`<rect x="${sx.toFixed(1)}" y="${mt}" width="${(ex - sx).toFixed(1)}" height="${plotH}"
      fill="var(--status-warning)" opacity="0.14"/>`);
  }

  niceTicks(ylo, yhi, 4).forEach((t) => {
    parts.push(`<line x1="${ml}" y1="${y(t).toFixed(1)}" x2="${w - mr}" y2="${y(t).toFixed(1)}"
      stroke="var(--gridline)" stroke-width="1"/>`);
    parts.push(`<text x="${ml - 9}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end"
      font-size="12" fill="var(--text-muted)">${FMT.format(Math.round(t))}</text>`);
  });

  if (fc.length) {
    const up = fc.map((d) => `${x(miOf(d[0])).toFixed(1)},${yc(d[3]).toFixed(1)}`);
    const dn = fc.map((d) => `${x(miOf(d[0])).toFixed(1)},${yc(d[2]).toFixed(1)}`).reverse();
    const anchor = hist.length
      ? `${x(miOf(hist[hist.length - 1][0])).toFixed(1)},${y(hist[hist.length - 1][1]).toFixed(1)} ` : "";
    parts.push(`<polygon points="${anchor}${up.join(" ")} ${dn.join(" ")}" fill="var(--series-1-soft)" clip-path="url(#pc)"/>`);
  }

  if (hist.length) {
    const pts = hist.map((d) => ({ mi: miOf(d[0]), sx: x(miOf(d[0])), sy: y(d[1]) }));
    parts.push(`<path d="${pathWithGaps(pts)}" fill="none" stroke="var(--series-1)" stroke-width="2"
      stroke-linejoin="round" stroke-linecap="round" clip-path="url(#pc)"/>`);
  }
  if (fc.length) {
    const start = hist.length
      ? `M${x(miOf(hist[hist.length - 1][0])).toFixed(1)},${y(hist[hist.length - 1][1]).toFixed(1)}`
      : `M${x(miOf(fc[0][0])).toFixed(1)},${y(fc[0][1]).toFixed(1)}`;
    parts.push(`<path d="${start}${fc.map((d) => `L${x(miOf(d[0])).toFixed(1)},${y(d[1]).toFixed(1)}`).join("")}"
      fill="none" stroke="var(--series-1)" stroke-width="2" stroke-dasharray="6 4"
      stroke-linejoin="round" stroke-linecap="round" clip-path="url(#pc)"/>`);
  }

  for (let mi = Math.ceil(mi0 / 12) * 12; mi <= mi1; mi += 12) {
    parts.push(`<text x="${x(mi).toFixed(1)}" y="${h - 8}" text-anchor="middle"
      font-size="11.5" fill="var(--text-muted)">${Math.floor(mi / 12)}</text>`);
  }
  parts.push(`<line x1="${ml}" y1="${mt + plotH}" x2="${w - mr}" y2="${mt + plotH}" stroke="var(--axis)" stroke-width="1"/>`);
  parts.push(`<rect id="hoverLayer" x="${ml}" y="${mt}" width="${plotW}" height="${plotH}" fill="transparent" style="cursor:crosshair"/>`);
  parts.push(`<line id="crosshair" x1="0" y1="${mt}" x2="0" y2="${mt + plotH}" stroke="var(--axis)" stroke-width="1" opacity="0"/>`);
  parts.push(`<circle id="hoverDot" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2" opacity="0"/>`);

  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.innerHTML = parts.join("");
  chartPoints = [
    ...hist.map((d) => ({ ym: d[0], isFc: false, sx: x(miOf(d[0])), sy: y(d[1]), d })),
    ...fc.map((d) => ({ ym: d[0], isFc: true, sx: x(miOf(d[0])), sy: y(d[1]), d })),
  ];
  bindHover();
}

function bindHover() {
  const svg = $("chart");
  const layer = svg.querySelector("#hoverLayer");
  const cross = svg.querySelector("#crosshair");
  const dot = svg.querySelector("#hoverDot");
  const tip = $("tooltip");
  if (!layer) return;

  const move = (evt) => {
    const rect = svg.getBoundingClientRect();
    const px = evt.touches ? evt.touches[0].clientX : evt.clientX;
    const vx = ((px - rect.left) / rect.width) * CHART.w;
    let best = chartPoints[0];
    for (const p of chartPoints) if (Math.abs(p.sx - vx) < Math.abs(best.sx - vx)) best = p;
    cross.setAttribute("x1", best.sx); cross.setAttribute("x2", best.sx); cross.setAttribute("opacity", "1");
    dot.setAttribute("cx", best.sx); dot.setAttribute("cy", best.sy); dot.setAttribute("opacity", "1");
    tip.innerHTML = `<div class="t-ym">${ymKo(miOf(best.ym))}${best.isFc ? " (예측)" : ""}</div>` +
      (best.isFc
        ? `<div class="t-row"><span>예측</span><b>${won(best.d[1])}원</b></div>
           <div class="t-row"><span>범위</span><b>${won(best.d[2])}~${won(best.d[3])}</b></div>
           <div class="t-row"><span>폭등확률</span><b>${(best.d[4] * 100).toFixed(0)}%</b></div>`
        : `<div class="t-row"><span>실제</span><b>${won(best.d[1])}원</b></div>`);
    tip.classList.add("show");
    const left = (best.sx / CHART.w) * rect.width;
    tip.style.left = Math.min(Math.max(left + 14, 0), rect.width - tip.offsetWidth) + "px";
    tip.style.top = (best.sy / CHART.h) * rect.height + "px";
  };
  layer.addEventListener("mousemove", move);
  layer.addEventListener("touchmove", (e) => { move(e); e.preventDefault(); }, { passive: false });
  layer.addEventListener("mouseleave", () => {
    cross.setAttribute("opacity", "0"); dot.setAttribute("opacity", "0"); tip.classList.remove("show");
  });
}

function drawAccuracy(c) {
  const list = [
    ["교차검증 (2020~2025)", c.cv_mape, c.cv_base_mape],
    c.v2025 && ["2025년 검증", c.v2025[0], c.v2025[1]],
    c.v2026 && ["2026년 실적 대조", c.v2026[0], c.v2026[1]],
  ].filter(Boolean);
  const max = Math.max(...list.flatMap((r) => [r[1], r[2]])) * 1.12;
  $("accuracy").innerHTML =
    `<p class="desc" style="margin:0 0 8px">이 조합의 예측이 과거에 얼마나 맞았는지 — 막대가 짧을수록 정확합니다.</p>` +
    list.map(([n, m, b]) => `
      <div class="acc-row">
        <span class="name">${n}</span>
        <span class="acc-bar-track"><span class="acc-bar" style="width:${(m / max * 100).toFixed(1)}%"></span></span>
        <span class="val">±${m.toFixed(1)}%</span>
      </div>
      <div class="acc-row" style="margin-bottom:14px">
        <span class="name" style="color:var(--text-muted);font-size:12px">└ 단순 예측 기준</span>
        <span class="acc-bar-track"><span class="acc-bar baseline" style="width:${(b / max * 100).toFixed(1)}%"></span></span>
        <span class="val" style="color:var(--text-muted)">±${b.toFixed(1)}%</span>
      </div>`).join("");
}

function niceTicks(lo, hi, count) {
  const raw = (hi - lo) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  const step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(t);
  return out;
}

init();
