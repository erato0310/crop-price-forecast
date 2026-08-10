/* 전북 농산물 가격예측 — 프런트엔드
   서버 없음: data/app_data.json(사전 계산된 예측) 하나만 읽어 렌더링한다.
   차트는 외부 라이브러리 없이 SVG를 직접 그린다(오프라인·정적 호스팅에서 그대로 동작). */

const CHART = { w: 1000, h: 380, ml: 62, mr: 16, mt: 14, mb: 30 };
const FMT = new Intl.NumberFormat("ko-KR");

let DATA = null;
let rangeMonths = 48;
let sel = { crop: null, county: null };

/* ── 유틸 ─────────────────────────────────────── */
const $ = (id) => document.getElementById(id);
const won = (v) => FMT.format(Math.round(v));
const ymLabel = (ym) => {
  const [y, m] = ym.split("-");
  return `${y.slice(2)}년 ${Number(m)}월`;
};
const comboKey = () => `${sel.crop}|${sel.county}`;
const combo = () => DATA.combos[comboKey()];
const cropName = (id) => (DATA.crops.find((c) => c.id === id) || {}).name || id;
const countyName = (id) => (DATA.counties.find((c) => c.id === id) || {}).name || id;

/* 폭등확률 → 상태(색은 보조, 항상 라벨과 함께 쓴다) */
function riskOf(p) {
  if (p >= 0.6) return { cls: "critical", label: "높음" };
  if (p >= 0.3) return { cls: "warning", label: "보통" };
  return { cls: "good", label: "낮음" };
}

/* ── 초기화 ───────────────────────────────────── */
async function init() {
  const res = await fetch("data/app_data.json");
  DATA = await res.json();

  $("updated").textContent =
    `${DATA.meta.last_actual_ym.replace("-", "년 ")}월 거래 기준 · ${DATA.meta.n_combos}개 조합`;

  sel.crop = DATA.crops[0].id;
  fillCropSelect();
  fillCountySelect();
  bindEvents();
  render();
}

function fillCropSelect() {
  $("cropSel").innerHTML = DATA.crops
    .map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
  $("cropSel").value = sel.crop;
}

/* 선택한 작물에 실제로 예측이 있는 시군만 노출 — 빈 화면이 나오지 않게 한다 */
function fillCountySelect() {
  const avail = DATA.counties.filter((c) => DATA.combos[`${sel.crop}|${c.id}`]);
  $("countySel").innerHTML = avail
    .map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
  if (!avail.some((c) => c.id === sel.county)) sel.county = avail[0].id;
  $("countySel").value = sel.county;
}

function bindEvents() {
  $("cropSel").addEventListener("change", (e) => {
    sel.crop = e.target.value;
    fillCountySelect();
    render();
  });
  $("countySel").addEventListener("change", (e) => {
    sel.county = e.target.value;
    render();
  });
  $("rangeGroup").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    rangeMonths = Number(btn.dataset.months);
    [...e.currentTarget.children].forEach((b) =>
      b.setAttribute("aria-pressed", String(b === btn)));
    render();
  });
  $("tableToggle").addEventListener("click", (e) => {
    const wrap = $("tableWrap");
    const open = wrap.hasAttribute("hidden");
    wrap.toggleAttribute("hidden", !open);
    e.target.setAttribute("aria-expanded", String(open));
    e.target.textContent = open ? "표 닫기" : "표로 보기";
  });
  $("themeToggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const isDark = cur ? cur === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", isDark ? "light" : "dark");
    render();
  });
  addEventListener("resize", () => positionTooltipHidden());
}

/* ── 렌더 ─────────────────────────────────────── */
function render() {
  const c = combo();
  if (!c) return;
  renderNotice(c);
  renderStats(c);
  renderChart(c);
  renderTable(c);
  renderAccuracy(c);
  renderRegion();
}

/* 시계열이 일찍 끊긴 조합은 조용히 넘어가지 않고 눈에 띄게 알린다 */
function renderNotice(c) {
  const el = $("notice");
  const lastActual = c.hist[c.hist.length - 1][0];
  const msgs = [];
  if (lastActual < DATA.meta.last_actual_ym) {
    msgs.push(`<div><strong>이 조합은 최근 거래 기록이 없습니다.</strong> ` +
      `마지막 실측이 ${ymLabel(lastActual)}이라, 그 이후 예측은 실제 시세를 반영하지 못할 수 있습니다.</div>`);
  }
  if (c.src === "gpj") {
    msgs.push(`<div><strong>산지공판장 정산가격 기준입니다.</strong> ` +
      `이 시군은 도매시장 거래 표본이 부족해 공판장 정산가를 대신 사용했습니다 — 다른 시군과 가격 수준을 직접 비교하지 마세요.</div>`);
  }
  if (c.n_obs < 60) {
    msgs.push(`<div><strong>표본이 적습니다(${c.n_obs}개월).</strong> ` +
      `데이터가 두터운 조합보다 예측이 불안정할 수 있습니다.</div>`);
  }
  el.innerHTML = msgs.join("");
  el.classList.toggle("show", msgs.length > 0);
}

function renderStats(c) {
  const lastActual = c.hist[c.hist.length - 1];
  const next = c.fc[0];
  const six = c.fc[Math.min(5, c.fc.length - 1)];
  const chg = ((next[1] - lastActual[1]) / lastActual[1]) * 100;
  const risk = riskOf(next[4]);
  const dirCls = chg > 0 ? "up" : chg < 0 ? "down" : "";
  const arrow = chg > 0 ? "▲" : chg < 0 ? "▼" : "―";

  $("stats").innerHTML = `
    <div class="tile">
      <div class="k">최근 실제 가격 · ${ymLabel(lastActual[0])}</div>
      <div class="v">${won(lastActual[1])}<span class="unit">원</span></div>
      <div class="sub">거래 단위당 물량가중 평균가</div>
    </div>
    <div class="tile">
      <div class="k">다음 달 예측 · ${ymLabel(next[0])}</div>
      <div class="v">${won(next[1])}<span class="unit">원</span></div>
      <div class="sub ${dirCls}">${arrow} 최근 대비 ${Math.abs(chg).toFixed(1)}%</div>
    </div>
    <div class="tile">
      <div class="k">가격 폭등 위험 · ${ymLabel(next[0])}</div>
      <div class="v risk ${risk.cls}">
        <span class="dot" aria-hidden="true"></span>
        <span class="label">${risk.label}</span>
      </div>
      <div class="sub">${(next[4] * 100).toFixed(0)}% · ${won(c.spike_threshold)}원 초과 확률</div>
    </div>
    <div class="tile">
      <div class="k">이 조합의 예측 정확도</div>
      <div class="v">±${c.cv_mape.toFixed(0)}<span class="unit">%</span></div>
      <div class="sub">${c.cv_mape < c.cv_base_mape
        ? `단순 예측(±${c.cv_base_mape.toFixed(0)}%)보다 정확`
        : `단순 예측(±${c.cv_base_mape.toFixed(0)}%)과 비슷`}</div>
    </div>`;
  $("chartDesc").textContent =
    `${countyName(sel.county)} ${cropName(sel.crop)} · ${six ? ymLabel(six[0]) + "까지의 전망을 함께 표시합니다" : ""}`;
  $("chartTitle").textContent = `${countyName(sel.county)} ${cropName(sel.crop)} 가격 추이와 전망`;
}

/* ── 차트 (SVG 직접 생성) ──────────────────────── */
let chartPoints = [];  // 호버 판정을 위한 화면좌표 캐시

const monthIdx = (ym) => {
  const [y, m] = ym.split("-").map(Number);
  return y * 12 + (m - 1);
};

/* 결측월이 있으면 선을 잇지 않고 끊는다 — 없는 데이터를 있는 것처럼 그리지 않기 위함 */
function pathWithGaps(points) {
  let d = "", prevIdx = null;
  for (const p of points) {
    d += (prevIdx !== null && p.mi === prevIdx + 1 ? "L" : "M") +
         `${p.sx.toFixed(1)},${p.sy.toFixed(1)}`;
    prevIdx = p.mi;
  }
  return d;
}

function renderChart(c) {
  const hist = c.hist.slice(-rangeMonths);
  const fc = c.fc;
  const svg = $("chart");
  const { w, h, ml, mr, mt, mb } = CHART;
  const plotW = w - ml - mr, plotH = h - mt - mb;

  // x축은 배열 순서가 아니라 실제 달력 월로 잡는다 — 결측월이 간격으로 보이게 된다
  const mi0 = monthIdx(hist[0][0]);
  const mi1 = monthIdx(fc.length ? fc[fc.length - 1][0] : hist[hist.length - 1][0]);
  const span = Math.max(1, mi1 - mi0);
  const x = (mi) => ml + ((mi - mi0) / span) * plotW;

  // y 범위: 실측·예측 중심선은 전부 포함하되, 신뢰구간은 앞 6개월치만 반영한다.
  // 먼 미래의 구간은 지수적으로 벌어져서(=그만큼 모른다는 뜻) 그대로 넣으면
  // 정작 봐야 할 실제 가격 변동이 납작하게 눌린다. 넘치는 구간은 clip으로 잘라 표시.
  const bandScope = fc.slice(0, 6);
  const values = [
    ...hist.map((d) => d[1]),
    ...fc.map((d) => d[1]),
    ...bandScope.map((d) => d[2]),
    ...bandScope.map((d) => d[3]),
  ];
  let lo = Math.min(...values), hi = Math.max(...values);
  const pad = (hi - lo) * 0.10 || hi * 0.1;
  lo = Math.max(0, lo - pad); hi = hi + pad;
  const y = (v) => mt + plotH - ((v - lo) / (hi - lo)) * plotH;
  const yc = (v) => Math.max(mt - 2, Math.min(mt + plotH + 2, y(v)));  // clip 보조

  const lastHist = hist[hist.length - 1];
  const lastHistMi = monthIdx(lastHist[0]);
  const parts = [];

  parts.push(`<defs><clipPath id="plotClip">
    <rect x="${ml}" y="${mt}" width="${plotW}" height="${plotH}"/></clipPath></defs>`);

  // 가로 그리드 (hairline, solid, 배경으로 물러남)
  niceTicks(lo, hi, 5).forEach((t) => {
    parts.push(`<line x1="${ml}" y1="${y(t).toFixed(1)}" x2="${w - mr}" y2="${y(t).toFixed(1)}"
      stroke="var(--gridline)" stroke-width="1"/>`);
    parts.push(`<text x="${ml - 9}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end"
      font-size="12" fill="var(--text-muted)">${FMT.format(Math.round(t))}</text>`);
  });

  const histPts = hist.map((d) => ({ mi: monthIdx(d[0]), sx: x(monthIdx(d[0])), sy: y(d[1]) }));
  const fcPts = fc.map((d) => ({ mi: monthIdx(d[0]), sx: x(monthIdx(d[0])), sy: y(d[1]) }));

  // 90% 예측 범위(면) — 화면 밖으로 나가는 부분은 clip
  if (fc.length) {
    const up = fc.map((d) => `${x(monthIdx(d[0])).toFixed(1)},${yc(d[3]).toFixed(1)}`);
    const dn = fc.map((d) => `${x(monthIdx(d[0])).toFixed(1)},${yc(d[2]).toFixed(1)}`).reverse();
    const anchor = `${x(lastHistMi).toFixed(1)},${y(lastHist[1]).toFixed(1)}`;
    parts.push(`<polygon points="${anchor} ${up.join(" ")} ${dn.join(" ")}"
      fill="var(--series-1-soft)" clip-path="url(#plotClip)"/>`);
  }

  // 실측/예측 경계
  parts.push(`<line x1="${x(lastHistMi).toFixed(1)}" y1="${mt}" x2="${x(lastHistMi).toFixed(1)}" y2="${mt + plotH}"
    stroke="var(--axis)" stroke-width="1" stroke-dasharray="3 3"/>`);
  parts.push(`<text x="${(x(lastHistMi) + 6).toFixed(1)}" y="${mt + 12}" font-size="11.5"
    fill="var(--text-muted)">여기부터 예측</text>`);

  // 실측 선 (2px 실선) — 결측월에서 끊김
  parts.push(`<path d="${pathWithGaps(histPts)}" fill="none" stroke="var(--series-1)"
    stroke-width="2" stroke-linejoin="round" stroke-linecap="round" clip-path="url(#plotClip)"/>`);

  // 예측 선 (같은 엔티티라 같은 색, 점선으로 상태만 구분)
  const fcPath = `M${x(lastHistMi).toFixed(1)},${y(lastHist[1]).toFixed(1)}` +
    fcPts.map((p) => `L${p.sx.toFixed(1)},${p.sy.toFixed(1)}`).join("");
  parts.push(`<path d="${fcPath}" fill="none" stroke="var(--series-1)" stroke-width="2"
    stroke-dasharray="6 4" stroke-linejoin="round" stroke-linecap="round" clip-path="url(#plotClip)"/>`);

  // 마지막 실측 지점만 직접 표시(표면색 링으로 겹침에도 읽히게)
  parts.push(`<circle cx="${x(lastHistMi).toFixed(1)}" cy="${y(lastHist[1]).toFixed(1)}" r="4.5"
    fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/>`);

  // x축 라벨: 연 경계(1월)를 눈금으로 — 간격이 규칙적으로 읽힌다
  const yearStep = span > 84 ? 2 : 1;
  for (let mi = Math.ceil(mi0 / 12) * 12; mi <= mi1; mi += 12 * yearStep) {
    parts.push(`<text x="${x(mi).toFixed(1)}" y="${h - 8}" text-anchor="middle"
      font-size="11.5" fill="var(--text-muted)">${Math.floor(mi / 12)}</text>`);
  }

  parts.push(`<line x1="${ml}" y1="${mt + plotH}" x2="${w - mr}" y2="${mt + plotH}"
    stroke="var(--axis)" stroke-width="1"/>`);

  // 호버 판정용 투명 레이어
  parts.push(`<rect id="hoverLayer" x="${ml}" y="${mt}" width="${plotW}" height="${plotH}"
    fill="transparent" style="cursor:crosshair"/>`);
  parts.push(`<line id="crosshair" x1="0" y1="${mt}" x2="0" y2="${mt + plotH}"
    stroke="var(--axis)" stroke-width="1" opacity="0"/>`);
  parts.push(`<circle id="hoverDot" r="5" fill="var(--series-1)" stroke="var(--surface-1)"
    stroke-width="2" opacity="0"/>`);

  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.innerHTML = parts.join("");
  svg.setAttribute("aria-label",
    `${countyName(sel.county)} ${cropName(sel.crop)}의 ${hist[0][0]}부터 ` +
    `${fc.length ? fc[fc.length - 1][0] : lastHist[0]}까지 가격 추이와 예측. ` +
    `표로 보기 버튼으로 같은 내용을 표로 확인할 수 있습니다.`);

  chartPoints = [
    ...hist.map((d) => ({ ym: d[0], isFc: false, sx: x(monthIdx(d[0])), sy: y(d[1]), d })),
    ...fc.map((d) => ({ ym: d[0], isFc: true, sx: x(monthIdx(d[0])), sy: y(d[1]), d })),
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
    for (const p of chartPoints) {
      if (Math.abs(p.sx - vx) < Math.abs(best.sx - vx)) best = p;
    }
    cross.setAttribute("x1", best.sx); cross.setAttribute("x2", best.sx);
    cross.setAttribute("opacity", "1");
    dot.setAttribute("cx", best.sx); dot.setAttribute("cy", best.sy);
    dot.setAttribute("opacity", "1");

    const rows = best.isFc
      ? `<div class="t-row"><span>예측</span><b>${won(best.d[1])}원</b></div>
         <div class="t-row"><span>범위</span><b>${won(best.d[2])}~${won(best.d[3])}</b></div>
         <div class="t-row"><span>폭등확률</span><b>${(best.d[4] * 100).toFixed(0)}%</b></div>`
      : `<div class="t-row"><span>실제</span><b>${won(best.d[1])}원</b></div>`;
    tip.innerHTML = `<div class="t-ym">${ymLabel(best.ym)}${best.isFc ? " (예측)" : ""}</div>${rows}`;
    tip.classList.add("show");

    const boxW = tip.offsetWidth;
    const left = (best.sx / CHART.w) * rect.width;
    tip.style.left = Math.min(Math.max(left + 14, 0), rect.width - boxW) + "px";
    tip.style.top = (best.sy / CHART.h) * rect.height + "px";
  };

  layer.addEventListener("mousemove", move);
  layer.addEventListener("touchmove", (e) => { move(e); e.preventDefault(); }, { passive: false });
  layer.addEventListener("mouseleave", () => {
    cross.setAttribute("opacity", "0");
    dot.setAttribute("opacity", "0");
    tip.classList.remove("show");
  });
}

function positionTooltipHidden() { $("tooltip").classList.remove("show"); }

/* ── 표 (차트와 동일 내용의 접근 가능한 대체 뷰) ── */
function renderTable(c) {
  $("fcTableBody").innerHTML = c.fc.map((d) => {
    const r = riskOf(d[4]);
    return `<tr>
      <td>${ymLabel(d[0])}</td>
      <td>${won(d[1])}원</td>
      <td>${won(d[2])} ~ ${won(d[3])}</td>
      <td><span class="pill ${r.cls}">${r.label} ${(d[4] * 100).toFixed(0)}%</span></td>
    </tr>`;
  }).join("");
}

/* ── 검증 성적 ────────────────────────────────── */
function renderAccuracy(c) {
  const rows = [
    ["교차검증 평균 (2020~2025)", c.cv_mape, c.cv_base_mape],
    c.v2025 && ["2025년 검증", c.v2025[0], c.v2025[1]],
    c.v2026 && ["2026년 실적 대조", c.v2026[0], c.v2026[1]],
  ].filter(Boolean);

  const max = Math.max(...rows.flatMap((r) => [r[1], r[2]])) * 1.12;
  $("accuracy").innerHTML = rows.map(([name, model, base]) => `
    <div class="acc-row">
      <span class="name">${name}</span>
      <span class="acc-bar-track"><span class="acc-bar" style="width:${(model / max * 100).toFixed(1)}%"></span></span>
      <span class="val">±${model.toFixed(1)}%</span>
    </div>
    <div class="acc-row" style="margin-bottom:16px">
      <span class="name" style="color:var(--text-muted);font-size:12.5px">└ 단순 예측 기준</span>
      <span class="acc-bar-track"><span class="acc-bar baseline" style="width:${(base / max * 100).toFixed(1)}%"></span></span>
      <span class="val" style="color:var(--text-muted)">±${base.toFixed(1)}%</span>
    </div>`).join("") +
    `<p class="desc" style="margin:6px 0 0">
      "단순 예측"은 그 달의 과거 평균가격을 그대로 답으로 쓰는 방식입니다.
      AI 모델의 막대가 더 짧으면 학습이 실제로 도움이 된 것입니다.</p>`;
}

/* ── 지역 추천 (현재 상추만 데이터 보유) ───────── */
function renderRegion() {
  const rows = DATA.region_recommend.filter((r) => r.crop_id === sel.crop);
  const card = $("regionCard");
  card.hidden = rows.length === 0;
  if (!rows.length) return;
  $("regionBody").innerHTML = rows.map((r) => `<tr>
      <td>${r.county}</td>
      <td>${r.suit_pct.toFixed(1)}%</td>
      <td>${r.high_pct.toFixed(1)}%</td>
      <td>${FMT.format(r.total_ha)} ha</td>
    </tr>`).join("");
}

/* ── 축 눈금 ──────────────────────────────────── */
function niceTicks(lo, hi, count) {
  const span = hi - lo;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const stepN = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  const step = stepN * mag;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(t);
  return out;
}

init();
