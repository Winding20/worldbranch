<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

const props = defineProps({
  //: 需要「聚光」的地区：其余地区压暗，只让这一个亮着
  focus: { type: String, default: "" },
  regions: { type: Array, default: () => [] },
  selected: { type: String, default: "" },
  scale: { type: String, default: "region" },
  factions: { type: Array, default: () => [] },
});
const emit = defineEmits(["select", "zoom-change"]);

const VB = { w: 900, h: 620 };
const svgRef = ref(null);
const transform = ref({ k: 1, x: 0, y: 0 });
const dragging = ref(false);
let last = { x: 0, y: 0 };

const REGION_COLORS = {
  guannei: [86, 118, 150],
  henan: [104, 132, 108],
  hebei: [138, 110, 92],
  hedong: [120, 104, 142],
  huainan: [96, 138, 132],
  jiangnan: [128, 116, 150],
  longyou: [102, 112, 128],
};

//: 势力配色：宏观视角下同势力的道用同一底色，边界的颜色变化即国界
const FACTION_COLORS = {
  tang: [92, 124, 158],
  fanzhen: [156, 104, 88],
};
const FALLBACK_FACTION_COLOR = [104, 118, 132];
const LABEL_AT = {
  guannei: [108.6, 33.4],
  henan: [114.8, 33.9],
  hebei: [116.6, 39.4],
  hedong: [112.3, 37.6],
  huainan: [117.0, 32.2],
  jiangnan: [116.8, 27.6],
  longyou: [97.0, 38.6],
};

function polygonsOf(region) {
  const geo = region && region.geo;
  if (!geo || !Array.isArray(geo.coordinates)) return [];
  if (geo.type === "Polygon") return [geo.coordinates];
  if (geo.type === "MultiPolygon") return geo.coordinates;
  return [];
}

const projection = computed(() => {
  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  props.regions.forEach((r) => {
    polygonsOf(r).forEach((poly) => {
      (poly[0] || []).forEach(([lon, lat]) => {
        if (lon < minLon) minLon = lon;
        if (lon > maxLon) maxLon = lon;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
      });
    });
  });
  if (!Number.isFinite(minLon)) return null;
  const pad = 26;
  const spanLon = Math.max(maxLon - minLon, 0.001);
  const spanLat = Math.max(maxLat - minLat, 0.001);
  const scale = Math.min((VB.w - pad * 2) / spanLon, (VB.h - pad * 2) / spanLat);
  const offX = (VB.w - spanLon * scale) / 2;
  const offY = (VB.h - spanLat * scale) / 2;
  return {
    toXY(lon, lat) {
      return [offX + (lon - minLon) * scale, offY + (maxLat - lat) * scale];
    },
  };
});

function pathData(region) {
  const proj = projection.value;
  if (!proj) return null;
  const parts = [];
  polygonsOf(region).forEach((poly) => {
    const ring = poly[0];
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

const shapes = computed(() =>
  props.regions
    .map((region) => ({ region, d: pathData(region) }))
    .filter((s) => s.d)
);

function baseColor(key) {
  const c = REGION_COLORS[key] || [104, 118, 132];
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

/** 宏观尺度按势力着色，细尺度按道着色。 */
const macro = computed(() => props.scale === "world" || props.scale === "nation");

//: 聚光：非焦点地区压暗，焦点地区保持原色并加一圈金边
const focusShape = computed(() =>
  props.focus ? shapes.value.find((s) => s.region.region_key === props.focus) : null
);

function dimOf(regionKey) {
  if (!props.focus) return 1;
  return regionKey === props.focus ? 1 : 0.22;
}

function regionFill(region) {
  if (!macro.value) return baseColor(region.region_key);
  const c = FACTION_COLORS[region.faction_key] || FALLBACK_FACTION_COLOR;
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function factionName(key) {
  const f = props.factions.find((x) => x.key === key);
  return f ? f.name : key || "—";
}

/** 宏观视角下只在治所标一个势力名，避免每个道都写一遍。 */
const factionLabels = computed(() => {
  if (!macro.value || !projection.value) return [];
  const seen = new Set();
  const out = [];
  props.regions.forEach((r) => {
    const key = r.faction_key || "unknown";
    if (seen.has(key)) return;
    seen.add(key);
    const capital = props.factions.find((f) => f.key === key)?.capital_region_key;
    const anchor = props.regions.find((x) => x.region_key === capital) || r;
    const [x, y] = projection.value.toXY(anchor.lon, anchor.lat);
    out.push({ key, name: factionName(key), x, y });
  });
  return out;
});

function stressAlpha(price) {
  const t = Math.max(0, Math.min(((price || 1) - 1.0) / 1.6, 1));
  return +(t * 0.62).toFixed(3);
}

function labelPos(region) {
  const proj = projection.value;
  if (!proj) return [0, 0];
  const anchor = LABEL_AT[region.region_key];
  return anchor ? proj.toXY(anchor[0], anchor[1]) : proj.toXY(region.lon, region.lat);
}

const layerTransform = computed(
  () => `translate(${transform.value.x},${transform.value.y}) scale(${transform.value.k})`
);

function zoomAt(factor, clientX, clientY) {
  const svg = svgRef.value;
  if (!svg) return;
  const rect = svg.getBoundingClientRect();
  const px = clientX != null ? clientX - rect.left : rect.width / 2;
  const py = clientY != null ? clientY - rect.top : rect.height / 2;
  const sx = (px / rect.width) * VB.w;
  const sy = (py / rect.height) * VB.h;
  const { k, x, y } = transform.value;
  const next = Math.min(Math.max(k * factor, 0.6), 14);
  const ratio = next / k;
  transform.value = { k: next, x: sx - (sx - x) * ratio, y: sy - (sy - y) * ratio };
  emit("zoom-change", next);
}

function onWheel(e) {
  e.preventDefault();
  zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY);
}

function onMouseDown(e) {
  dragging.value = true;
  last = { x: e.clientX, y: e.clientY };
}

function onMouseMove(e) {
  if (!dragging.value) return;
  const rect = svgRef.value.getBoundingClientRect();
  const dx = ((e.clientX - last.x) / rect.width) * VB.w;
  const dy = ((e.clientY - last.y) / rect.height) * VB.h;
  last = { x: e.clientX, y: e.clientY };
  transform.value = {
    k: transform.value.k,
    x: transform.value.x + dx,
    y: transform.value.y + dy,
  };
}

function onMouseUp() {
  dragging.value = false;
}

function reset() {
  transform.value = { k: 1, x: 0, y: 0 };
  emit("zoom-change", 1);
}

onMounted(() => {
  window.addEventListener("mousemove", onMouseMove);
  window.addEventListener("mouseup", onMouseUp);
});
onBeforeUnmount(() => {
  window.removeEventListener("mousemove", onMouseMove);
  window.removeEventListener("mouseup", onMouseUp);
});

defineExpose({ zoomAt, reset });
</script>

<template>
  <div class="map-wrap">
    <svg
      ref="svgRef"
      class="map-svg"
      :class="{ dragging }"
      :viewBox="`0 0 ${VB.w} ${VB.h}`"
      preserveAspectRatio="xMidYMid meet"
      @wheel="onWheel"
      @mousedown="onMouseDown"
    >
      <g :transform="layerTransform">
        <!-- 第一遍：描边，第二遍：填充盖住内部省界 -->
        <path
          v-for="s in shapes"
          :key="`stroke-${s.region.region_key}`"
          :d="s.d"
          :fill="regionFill(s.region)"
          stroke="#0a0f14"
          stroke-width="1.6"
          stroke-linejoin="round"
        />
        <path
          v-for="s in shapes"
          :key="`fill-${s.region.region_key}`"
          :d="s.d"
          :fill="regionFill(s.region)"
          :opacity="dimOf(s.region.region_key)"
          stroke="none"
        />
        <!-- 粮价压力叠加 -->
        <path
          v-for="s in shapes.filter((x) => stressAlpha(x.region.price_index) > 0)"
          :key="`stress-${s.region.region_key}`"
          :d="s.d"
          fill="#d63e2a"
          :fill-opacity="stressAlpha(s.region.price_index)"
          :opacity="dimOf(s.region.region_key)"
          stroke="none"
          pointer-events="none"
        />
        <!-- 交互层 -->
        <path
          v-for="s in shapes"
          :key="`hit-${s.region.region_key}`"
          :d="s.d"
          fill="transparent"
          class="region-hit"
          @click="emit('select', s.region.region_key)"
        >
          <title>{{ s.region.name }}</title>
        </path>
        <!-- 选中高亮 -->
        <path
          v-if="shapes.find((s) => s.region.region_key === selected)"
          :d="shapes.find((s) => s.region.region_key === selected).d"
          fill="none"
          stroke="#4aa8d8"
          stroke-width="3"
          pointer-events="none"
        />
        <!-- 聚光：只把出事的那个地区圈出来 -->
        <path
          v-if="focusShape"
          :d="focusShape.d"
          fill="none"
          stroke="#d8a24a"
          stroke-width="4"
          stroke-linejoin="round"
          class="spotlight-ring"
          pointer-events="none"
        />

        <!-- 标签：宏观尺度只标势力，细尺度标每个道 -->
        <g v-if="macro" pointer-events="none">
          <g v-for="f in factionLabels" :key="`fl-${f.key}`">
            <text :x="f.x" :y="f.y - 2" class="faction-label" text-anchor="middle">
              {{ f.name }}
            </text>
          </g>
        </g>
        <g v-else v-for="s in shapes" :key="`label-${s.region.region_key}`" pointer-events="none">
          <text
            :x="labelPos(s.region)[0]"
            :y="labelPos(s.region)[1] - 2"
            class="region-label"
            text-anchor="middle"
          >
            {{ s.region.name }}
          </text>
          <text
            :x="labelPos(s.region)[0]"
            :y="labelPos(s.region)[1] + 14"
            class="region-sub"
            text-anchor="middle"
          >
            粮价 {{ (s.region.price_index || 1).toFixed(2) }}
          </text>
        </g>
      </g>
    </svg>
    <div class="map-hint">滚轮缩放 · 拖拽平移 · 点击地区查看详情与干预</div>
    <div class="zoom-group">
      <button title="放大" @click="zoomAt(1.3)">＋</button>
      <button title="缩小" @click="zoomAt(1 / 1.3)">－</button>
      <button title="复位" @click="reset">⟲</button>
    </div>
  </div>
</template>

<style scoped>
.map-wrap { position: relative; flex: 1; min-height: 0; overflow: hidden; }
.map-svg { width: 100%; height: 100%; display: block; cursor: grab; }
.map-svg.dragging { cursor: grabbing; }
.region-hit { cursor: pointer; }
.region-label {
  font-size: 13px;
  fill: #eef4f9;
  paint-order: stroke;
  stroke: rgba(0, 0, 0, 0.65);
  stroke-width: 3px;
  user-select: none;
}
.region-sub {
  font-size: 10.5px;
  fill: #c6d6e2;
  paint-order: stroke;
  stroke: rgba(0, 0, 0, 0.6);
  stroke-width: 2.5px;
  user-select: none;
}
.faction-label {
  font-size: 17px;
  font-weight: 700;
  fill: #f2f7fb;
  paint-order: stroke;
  stroke: rgba(0, 0, 0, 0.7);
  stroke-width: 4px;
  letter-spacing: 2px;
  user-select: none;
}
.map-hint {
  position: absolute;
  left: 14px;
  bottom: 12px;
  font-size: 11px;
  color: #8fa1b0;
  background: rgba(15, 20, 25, 0.75);
  padding: 5px 10px;
  border-radius: 8px;
  pointer-events: none;
}
.zoom-group {
  position: absolute;
  right: 14px;
  top: 12px;
  display: flex;
  gap: 4px;
}
.zoom-group button {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid #2a3540;
  background: rgba(29, 38, 47, 0.9);
  color: #dfe7ee;
  font-size: 15px;
  cursor: pointer;
}
.zoom-group button:hover { border-color: #4aa8d8; color: #4aa8d8; }
</style>