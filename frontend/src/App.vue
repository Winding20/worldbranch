<script setup>
import { onMounted, ref } from "vue";
import { api } from "./api.js";
import MapView from "./components/MapView.vue";
import EventFeed from "./components/EventFeed.vue";
import RegionDetail from "./components/RegionDetail.vue";
import BranchCompare from "./components/BranchCompare.vue";

const WORLD = "tang_750";
const PRECISIONS = [
  { key: "macro", name: "宏观推演", desc: "国家与地区关系" },
  { key: "standard", name: "标准模拟", desc: "重要地区与势力" },
  { key: "fine", name: "精细模拟", desc: "地方经济与人物" },
  { key: "deep", name: "深度模拟", desc: "个体与局部交互" },
];

const branch = ref(null);
const regions = ref([]);
const factions = ref([]);
const events = ref([]);
const precision = ref("standard");
const scope = ref("region");
const selected = ref("");
const busy = ref(false);
const message = ref("底层按规则逐月计算，不是整段交给 AI 总结。");
const error = ref("");
const view = ref("sim");

const region = ref(null);

function selectRegion(key) {
  selected.value = key;
  region.value = regions.value.find((r) => r.region_key === key) || null;
}

async function loadState() {
  const data = await api.branchState(branch.value.id);
  branch.value = data.branch;
  regions.value = data.regions;
  factions.value = data.factions;
  precision.value = data.branch.precision;
  if (selected.value) selectRegion(selected.value);
}

async function loadEvents() {
  events.value = await api.events(branch.value.id);
}

async function ensureBranch() {
  const list = await api.branches(WORLD);
  if (Array.isArray(list) && list.length) return list[0];
  return api.createBranch(WORLD, {
    precision: precision.value,
    seed: 1,
    name: "唐朝·主时间线",
  });
}

async function boot() {
  try {
    branch.value = await ensureBranch();
    await loadState();
    await loadEvents();
  } catch (err) {
    error.value = `初始化失败：${err.message}`;
  }
}

async function advance(months) {
  if (!branch.value || busy.value) return;
  busy.value = true;
  message.value = "正在按规则推进…";
  try {
    const report = await api.advance(branch.value.id, months, precision.value);
    await loadState();
    await loadEvents();
    message.value = `已推进 ${report.months} 个月（${report.from_date} → ${report.to_date}），期间产生 ${report.event_count} 条事件。`;
  } catch (err) {
    message.value = `推进失败：${err.message}`;
  } finally {
    busy.value = false;
  }
}

async function setPrecision(key) {
  precision.value = key;
  message.value = `下次推进将使用「${PRECISIONS.find((p) => p.key === key).name}」；精度对整个世界统一生效。`;
}

async function onAct(action, r) {
  const monthly = r.population * 0.42;
  let payload;
  if (action === "shock") {
    payload = { kind: "shock", region_key: r.region_key, params: { damage_ratio: 0.6 } };
  } else if (action === "relief") {
    payload = {
      kind: "relief",
      region_key: r.region_key,
      params: { amount: Math.round(monthly * 0.8) },
    };
  } else {
    const delta = action === "tax-up" ? 0.02 : -0.02;
    const rate = Math.max(0, Math.min(0.5, (r.tax_rate || 0) + delta));
    payload = { kind: "tax", region_key: r.region_key, params: { rate } };
  }
  try {
    const event = await api.act(branch.value.id, payload);
    message.value = `已记录干预：${event.title}`;
    await loadState();
    await loadEvents();
  } catch (err) {
    message.value = `干预失败：${err.message}`;
  }
}

onMounted(boot);
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark">WB</span>
      <div>
        <h1>WorldBranch</h1>
        <p>平行世界推演实验室</p>
      </div>
    </div>
    <div v-if="branch" class="branch-meta">
      <nav class="view-tabs">
        <button :class="{ active: view === 'sim' }" @click="view = 'sim'">推演</button>
        <button :class="{ active: view === 'compare' }" @click="view = 'compare'">分支对比</button>
      </nav>
      <span class="chip">时间 <b>{{ branch.current_date }}</b></span>
      <span class="chip">精度 <b>{{ PRECISIONS.find((p) => p.key === branch.precision)?.name }}</b></span>
      <span class="chip">已推进 <b>{{ branch.tick_index }}</b> 月</span>
      <a class="chip link" href="/legacy">旧版界面</a>
    </div>
  </header>

  <main v-if="view === 'compare'" class="compare-main">
    <BranchCompare :world="WORLD" :current-branch-id="branch ? branch.id : null" />
  </main>

  <main v-else class="layout">
    <section class="map-panel">
      <div class="map-toolbar">
        <div class="scale-group">
          <label for="scope">观察尺度</label>
          <select id="scope" v-model="scope">
            <option value="world">世界级</option>
            <option value="nation">国家级</option>
            <option value="region">地区级</option>
            <option value="local">局部级</option>
          </select>
        </div>
        <div class="legend">
          <span><i style="background:#5a7a96"></i>道界</span>
          <span><i style="background:rgba(214,62,42,.25)"></i>粮价偏高</span>
          <span><i style="background:rgba(214,62,42,.62)"></i>严重缺粮</span>
        </div>
      </div>
      <MapView :regions="regions" :selected="selected" @select="selectRegion" />
    </section>

    <aside class="side-panel">
      <div class="panel-block">
        <h2>模拟控制</h2>
        <div class="precision-grid">
          <button
            v-for="p in PRECISIONS"
            :key="p.key"
            :class="{ active: precision === p.key }"
            @click="setPrecision(p.key)"
          >
            <b>{{ p.name }}</b><span>{{ p.desc }}</span>
          </button>
        </div>
        <div class="advance-row">
          <button class="advance" :disabled="busy" @click="advance(1)">推进 1 月</button>
          <button class="advance" :disabled="busy" @click="advance(3)">推进 3 月</button>
          <button class="advance" :disabled="busy" @click="advance(12)">推进 12 月</button>
        </div>
        <p class="hint">{{ message }}</p>
        <p v-if="error" class="hint error">{{ error }}</p>
      </div>

      <div class="panel-block">
        <h2>地区详情</h2>
        <RegionDetail :region="region" @act="onAct" />
      </div>

      <div class="panel-block grow">
        <h2>事件流 <span class="count">{{ events.length }}</span></h2>
        <EventFeed
          :branch-id="branch ? branch.id : null"
          :events="events"
          :scope="scope"
          @select-region="selectRegion"
        />
      </div>
    </aside>
  </main>
</template>