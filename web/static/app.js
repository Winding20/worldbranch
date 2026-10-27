/* global window, document */
(() => {
  "use strict";

  const state = {
    branchId: null,
    precision: "standard",
    world: "tang_750",
    regions: [],
    factions: [],
    events: [],
    selected: null,
    scope: "region",
    projection: null,
    transform: { k: 1, x: 0, y: 0 },
  };

  const MAX_MONTHS = 120;
  const VB = { w: 900, h: 620 };

  const $ = (id) => document.getElementById(id);
  const api = async (url, options = {}) => {
    const resp = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.error || `请求失败 ${resp.status}`);
    }
    return resp.json();
  };

  // ---------------------------------------------------------------- //
  // 投影：经纬度 -> SVG 坐标
  // ---------------------------------------------------------------- //

  /** 取出一个地区的所有多边形（每个多边形是「环的数组」，环是 [lon,lat] 列表）。 */
  function polygonsOf(region) {
    const geo = region.geo;
    if (!geo || !Array.isArray(geo.coordinates)) return [];
    if (geo.type === "Polygon") return [geo.coordinates];
    if (geo.type === "MultiPolygon") return geo.coordinates;
    return [];
  }

  function buildProjection(regions) {
    let minLon = Infinity;
    let maxLon = -Infinity;
    let minLat = Infinity;
    let maxLat = -Infinity;

    regions.forEach((r) => {
      polygonsOf(r).forEach((poly) => {
        (poly[0] || []).forEach(([lon, lat]) => {
          if (lon < minLon) minLon = lon;
          if (lon > maxLon) maxLon = lon;
          if (lat < minLat) minLat = lat;
          if (lat > maxLat) maxLat = lat;
        });
      });
      if (Number.isFinite(r.lon) && Number.isFinite(r.lat)) {
        if (r.lon < minLon) minLon = r.lon;
        if (r.lon > maxLon) maxLon = r.lon;
        if (r.lat < minLat) minLat = r.lat;
        if (r.lat > maxLat) maxLat = r.lat;
      }
    });

    if (!Number.isFinite(minLon)) return null;

    const pad = 26;
    const spanLon = Math.max(maxLon - minLon, 0.001);
    const spanLat = Math.max(maxLat - minLat, 0.001);
    const scale = Math.min((VB.w - pad * 2) / spanLon, (VB.h - pad * 2) / spanLat);
    const offX = (VB.w - spanLon * scale) / 2;
    const offY = (VB.h - spanLat * scale) / 2;

    return {
      minLon,
      minLat,
      maxLon,
      maxLat,
      scale,
      toXY(lon, lat) {
        return [offX + (lon - minLon) * scale, offY + (maxLat - lat) * scale];
      },
    };
  }

  // ---------------------------------------------------------------- //
  // 配色：道身份色 + 粮价压力叠加
  // ---------------------------------------------------------------- //
  // 一个「道」由多个现代省多边形拼成。如果所有道用同一种数据色，
  // 内部接缝被第二遍填充盖掉后，整张图会糊成一团、分不清边界。
  // 所以底色用「道身份色」区分势力范围，粮价压力另用红色叠加表达。
  const REGION_COLORS = {
    guannei: [86, 118, 150],
    henan: [104, 132, 108],
    hebei: [138, 110, 92],
    hedong: [120, 104, 142],
    huainan: [96, 138, 132],
    jiangnan: [128, 116, 150],
    longyou: [102, 112, 128],
  };
  const FALLBACK_COLOR = [104, 118, 132];

  //: 标签位置。治所（如扬州、越州）多在辖区边缘，直接用会把字压到邻道去，
  //: 所以给每个道单独指定一个"文字锚点"。
  const LABEL_AT = {
    guannei: [108.6, 33.4],
    henan: [114.8, 33.9],
    hebei: [116.6, 39.4],
    hedong: [112.3, 37.6],
    huainan: [117.0, 32.2],
    jiangnan: [116.8, 27.6],
    longyou: [97.0, 38.6],
  };

  function baseColor(key) {
    const c = REGION_COLORS[key] || FALLBACK_COLOR;
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }

  /** 粮价压力：1.0 以下无叠加，越贵越红，最高 0.62 不透明。 */
  function stressAlpha(price) {
    const t = Math.max(0, Math.min((price - 1.0) / 1.6, 1));
    return +(t * 0.62).toFixed(3);
  }

  // ---------------------------------------------------------------- //
  // 地图渲染
  // ---------------------------------------------------------------- //
  const NS = "http://www.w3.org/2000/svg";
  const el = (name, attrs = {}) => {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    return node;
  };

  /** 把一个地区的所有多边形拼成一条 path 的 d 属性（可能含多个子路径）。 */
  function pathData(region, proj) {
    const parts = [];
    polygonsOf(region).forEach((poly) => {
      const ring = poly[0]; // 只画外环；本数据集的孔洞可忽略
      if (!Array.isArray(ring) || ring.length < 3) return;
      const d = ring
        .map(([lon, lat], i) => {
          const [x, y] = proj.toXY(lon, lat);
          return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(" ");
      parts.push(d + " Z");
    });
    return parts.join(" ") || null;
  }

  function renderMap() {
    const layer = $("mapLayer");
    layer.innerHTML = "";
    if (!state.regions.length) return;

    state.projection = buildProjection(state.regions);
    if (!state.projection) return;
    const proj = state.projection;

    const shapes = state.regions
      .map((region) => ({ region, d: pathData(region, proj) }))
      .filter((s) => s.d);

    // 两遍绘制：先描边、后填充。
    // 一个「道」由多个现代省的多边形组成，内部接缝要靠第二遍填充盖掉，
    // 这样整条道看起来是一个整体，只有外轮廓留有描边。
    shapes.forEach(({ region, d }) => {
      layer.appendChild(
        el("path", {
          d,
          fill: baseColor(region.region_key),
          stroke: "#0a0f14",
          "stroke-width": 1.6,
          "stroke-linejoin": "round",
        })
      );
    });
    shapes.forEach(({ region, d }) => {
      layer.appendChild(
        el("path", {
          d,
          fill: baseColor(region.region_key),
          stroke: "none",
        })
      );
    });

    // 粮价压力叠加层：红色越浓，说明该道粮价越高
    shapes.forEach(({ region, d }) => {
      const alpha = stressAlpha(region.price_index || 1);
      if (alpha <= 0) return;
      layer.appendChild(
        el("path", {
          d,
          fill: `rgba(214, 62, 42, ${alpha})`,
          stroke: "none",
          "pointer-events": "none",
        })
      );
    });

    // 交互层：放在最上面接收点击
    shapes.forEach(({ region, d }) => {
      const path = el("path", {
        d,
        class: "region-path",
        fill: "transparent",
        stroke: "none",
        "data-key": region.region_key,
      });
      path.addEventListener("click", () => selectRegion(region.region_key));
      path.appendChild(el("title")).textContent = region.name;
      layer.appendChild(path);
    });

    // 选中高亮
    const selected = shapes.find((s) => s.region.region_key === state.selected);
    if (selected) {
      layer.appendChild(
        el("path", {
          d: selected.d,
          fill: "none",
          stroke: "#4aa8d8",
          "stroke-width": 3,
          "pointer-events": "none",
        })
      );
    }

    // 标签：位置用预设的文字锚点，避免压在邻道上
    shapes.forEach(({ region }) => {
      const anchor = LABEL_AT[region.region_key];
      const [cx, cy] = anchor
        ? proj.toXY(anchor[0], anchor[1])
        : proj.toXY(region.lon, region.lat);
      const label = el("text", {
        x: cx,
        y: cy - 2,
        class: "region-label",
        "text-anchor": "middle",
      });
      label.textContent = region.name;
      layer.appendChild(label);

      const sub = el("text", {
        x: cx,
        y: cy + 14,
        class: "region-sub",
        "text-anchor": "middle",
      });
      sub.textContent = `粮价 ${(region.price_index || 1).toFixed(2)}`;
      layer.appendChild(sub);
    });

    applyTransform();
    updateLegend();
  }

  function updateLegend() {
    $("legend").innerHTML = `
      <span><i style="background:#5a7a96"></i>道界</span>
      <span><i style="background:rgba(214,62,42,.25)"></i>粮价偏高</span>
      <span><i style="background:rgba(214,62,42,.62)"></i>严重缺粮</span>`;
  }

  function applyTransform() {
    const { k, x, y } = state.transform;
    $("mapLayer").setAttribute("transform", `translate(${x},${y}) scale(${k})`);
  }

  // ---------------------------------------------------------------- //
  // 缩放与平移
  // ---------------------------------------------------------------- //
  function zoomAt(factor, clientX, clientY) {
    const svg = $("map");
    const rect = svg.getBoundingClientRect();
    const px = clientX != null ? clientX - rect.left : rect.width / 2;
    const py = clientY != null ? clientY - rect.top : rect.height / 2;
    const sx = (px / rect.width) * VB.w;
    const sy = (py / rect.height) * VB.h;

    const { k, x, y } = state.transform;
    const next = Math.min(Math.max(k * factor, 0.6), 12);
    const ratio = next / k;
    state.transform = {
      k: next,
      x: sx - (sx - x) * ratio,
      y: sy - (sy - y) * ratio,
    };
    applyTransform();
  }

  function bindMapInteractions() {
    const svg = $("map");
    let dragging = false;
    let last = { x: 0, y: 0 };

    svg.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY);
      },
      { passive: false }
    );

    svg.addEventListener("mousedown", (e) => {
      dragging = true;
      last = { x: e.clientX, y: e.clientY };
      svg.classList.add("dragging");
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const rect = svg.getBoundingClientRect();
      const dx = ((e.clientX - last.x) / rect.width) * VB.w;
      const dy = ((e.clientY - last.y) / rect.height) * VB.h;
      last = { x: e.clientX, y: e.clientY };
      state.transform.x += dx;
      state.transform.y += dy;
      applyTransform();
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
      svg.classList.remove("dragging");
    });

    $("zoomIn").addEventListener("click", () => zoomAt(1.3));
    $("zoomOut").addEventListener("click", () => zoomAt(1 / 1.3));
    $("zoomReset").addEventListener("click", () => {
      state.transform = { k: 1, x: 0, y: 0 };
      applyTransform();
    });
  }

  // ---------------------------------------------------------------- //
  // 侧栏
  // ---------------------------------------------------------------- //
  function selectRegion(key) {
    state.selected = key;
    renderMap();
    renderRegionDetail();
  }

  function renderRegionDetail() {
    const box = $("regionDetail");
    const region = state.regions.find((r) => r.region_key === state.selected);
    if (!region) {
      box.className = "empty";
      box.textContent = "点击地图上的地区";
      return;
    }
    box.className = "";
    const q = region.data_quality || {};
    const tag = (field) => {
      const v = q[field];
      if (!v) return "";
      const label = { estimate: "估算", assumption: "假设", unknown: "未知", approximate: "近似" }[v] || v;
      return `<span class="quality-tag">${label}</span>`;
    };
    box.innerHTML = `
      <div class="kv"><span>名称</span><b>${region.name}</b></div>
      <div class="kv"><span>人口</span><b>${Number(region.population).toLocaleString()}${tag("population")}</b></div>
      <div class="kv"><span>存粮</span><b>${Math.round(region.grain_stock).toLocaleString()} 石</b></div>
      <div class="kv"><span>月产粮基数</span><b>${Math.round(region.farmland).toLocaleString()}${tag("farmland")}</b></div>
      <div class="kv"><span>粮价指数</span><b>${(region.price_index || 1).toFixed(2)}</b></div>
      <div class="kv"><span>民变指数</span><b>${(region.unrest || 0).toFixed(2)}</b></div>
      <div class="kv"><span>税率</span><b>${((region.tax_rate || 0) * 100).toFixed(0)}%</b></div>
      <div class="kv"><span>所属势力</span><b>${region.faction_key || "—"}</b></div>
    `;
  }

  function renderEvents() {
    const order = { local: 1, region: 2, nation: 3, world: 4 };
    const threshold = order[state.scope] || 1;
    const list = state.events.filter((e) => (order[e.scope] || 1) >= threshold);

    $("eventCount").textContent = String(list.length);
    const box = $("eventList");
    if (!list.length) {
      box.innerHTML = `<div class="empty">当前尺度下暂无事件，推进模拟试试。</div>`;
      return;
    }
    const scopeLabel = { local: "局部", region: "地区", nation: "国家", world: "世界" };
    box.innerHTML = list
      .map((e) => {
        const dots = Array.from({ length: 5 }, (_, i) => `<i class="${i < e.severity ? "on" : ""}"></i>`).join("");
        return `
          <div class="event-item" data-key="${e.region_keys && e.region_keys[0] ? e.region_keys[0] : ""}">
            <div class="row1">
              <span class="date">${e.game_date}</span>
              <span class="scope-tag ${e.scope}">${scopeLabel[e.scope] || e.scope}</span>
              <span class="severity-dots">${dots}</span>
            </div>
            <div class="title">${e.title}</div>
            <div class="summary">${e.summary}</div>
          </div>`;
      })
      .join("");

    box.querySelectorAll(".event-item").forEach((node) => {
      node.addEventListener("click", () => {
        const key = node.getAttribute("data-key");
        if (key) selectRegion(key);
      });
    });
  }

  function renderMeta(branch) {
    $("chipDate").innerHTML = `时间 <b>${branch.current_date}</b>`;
    $("chipPrecision").innerHTML = `精度 <b>${precisionLabel(branch.precision)}</b>`;
    $("chipTick").innerHTML = `已推进 <b>${branch.tick_index}</b> 月`;
    document.querySelectorAll("#precisionGrid button").forEach((b) => {
      b.classList.toggle("active", b.dataset.precision === branch.precision);
    });
  }

  function precisionLabel(p) {
    return { macro: "宏观推演", standard: "标准模拟", fine: "精细模拟", deep: "深度模拟" }[p] || p;
  }

  // ---------------------------------------------------------------- //
  // 数据加载
  // ---------------------------------------------------------------- //
  async function loadState() {
    const data = await api(`/api/branches/${state.branchId}/state`);
    state.regions = data.regions;
    state.factions = data.factions;
    renderMeta(data.branch);
    renderMap();
    renderRegionDetail();
  }

  async function loadEvents() {
    const data = await api(`/api/branches/${state.branchId}/events?limit=200`);
    state.events = data;
    renderEvents();
  }

  async function advance(months) {
    document.querySelectorAll(".advance").forEach((b) => (b.disabled = true));
    $("advanceHint").textContent = "正在按规则推进…";
    try {
      const report = await api(`/api/branches/${state.branchId}/advance`, {
        method: "POST",
        body: JSON.stringify({ months, precision: state.precision }),
      });
      await loadState();
      await loadEvents();
      $("advanceHint").textContent =
        `已推进 ${report.months} 个月（${report.from_date} → ${report.to_date}），` +
        `期间产生 ${report.event_count} 条事件。`;
    } catch (err) {
      $("advanceHint").textContent = `推进失败：${err.message}`;
    } finally {
      document.querySelectorAll(".advance").forEach((b) => (b.disabled = false));
    }
  }

  async function resolveBranch() {
    // 刷新页面时复用该世界最新的分支，避免每次刷新都新开一条时间线
    try {
      const list = await api(`/api/worlds/${state.world}/branches`);
      if (Array.isArray(list) && list.length) {
        const latest = list[0];
        state.precision = latest.precision;
        return latest;
      }
    } catch (err) {
      /* 没有分支就新建 */
    }
    return api(`/api/worlds/${state.world}/branches`, {
      method: "POST",
      body: JSON.stringify({
        precision: state.precision,
        seed: 1,
        name: "唐朝·主时间线",
      }),
    });
  }

  async function boot() {
    bindMapInteractions();
    $("scopeSelect").addEventListener("change", (e) => {
      state.scope = e.target.value;
      renderEvents();
    });
    $("precisionGrid").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-precision]");
      if (!btn) return;
      state.precision = btn.dataset.precision;
      document.querySelectorAll("#precisionGrid button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      $("advanceHint").textContent = `下次推进将使用「${precisionLabel(state.precision)}」；精度设置对整个世界统一生效。`;
    });
    document.querySelectorAll(".advance").forEach((btn) => {
      btn.addEventListener("click", () => advance(Number(btn.dataset.months)));
    });

    try {
      const branch = await resolveBranch();
      state.branchId = branch.id;
      await loadState();
      await loadEvents();
    } catch (err) {
      $("advanceHint").textContent = `初始化失败：${err.message}（请确认后端已建表并灌入世界数据）`;
    }
  }

  window.addEventListener("DOMContentLoaded", boot);
})();