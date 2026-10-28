<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { api } from "./api.js";
import MapView from "./components/MapView.vue";
import EventFeed from "./components/EventFeed.vue";
import RegionDetail from "./components/RegionDetail.vue";
import BranchCompare from "./components/BranchCompare.vue";
import AiPanel from "./components/AiPanel.vue";
import DecisionPanel from "./components/DecisionPanel.vue";
import { isMuted, toggleMuted } from "./sound.js";
import EndingCard from "./components/EndingCard.vue";

const WORLD = "tang_755";
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
const units = ref([]);
const manualScope = ref(false);
const decisions = ref([]);
const relations = ref([]);
const changes = ref([]);
const scenario = ref(null);
const lastReport = ref(null);
const ending = ref(null);
const decisionResult = ref(null);
const armies = ref({ armies: [], tang_total: 0, yan_total: 0 });
const loyalty = ref([]);
const historyStatus = ref({ fired: [], diverged: [] });
//: 右侧分组：决断 / 军事 / 人物 / 史实
const panel = ref("decide");
//: 音效开关（状态存在 localStorage，刷新后保持）
const muted = ref(isMuted());
function toggleSound() {
  muted.value = toggleMuted();
}
//: 侧栏抽屉（窄屏默认收起，宽屏默认展开）
const drawerOpen = ref(typeof window !== "undefined" && window.innerWidth >= 1024);
//: 决策浮层被"稍后再议"收起的标记
const overlayDismissed = ref(false);

//: 当前要处理的那一件事
const activeDecision = computed(() => decisions.value[0] || null);
const showOverlay = computed(
  () => Boolean(activeDecision.value) && !overlayDismissed.value
);

//: 决策浮层开着时，地图只照亮出事的地方
const spotlightRegion = computed(() => {
  if (showOverlay.value && activeDecision.value?.focus_region) {
    return activeDecision.value.focus_region;
  }
  return selected.value || "";
});

const tang = computed(() => factions.value.find((f) => f.faction_key === "tang"));
const allegiance = computed(
  () => relations.value.find((r) => r.from_key === "fanzhen") || null
);

//: 这盘棋的终点是广德元年（764），共 99 个月
const HORIZON_MONTHS = 99;
const progressPct = computed(() => {
  const done = branch.value ? branch.value.tick_index : 0;
  return Math.min(100, Math.round((done / HORIZON_MONTHS) * 100));
});
const monthsLeft = computed(() => {
  const done = branch.value ? branch.value.tick_index : 0;
  return Math.max(0, HORIZON_MONTHS - done);
});
//: 官职的显示名。数字与代码留在数据里，界面只给人读的字。
const RANK_LABELS = { 1: "一品", 2: "二品", 3: "三品", 4: "四品", 5: "五品" };
const KIND_LABELS = {
  military: "统兵",
  civil: "文职",
  envoy: "使职",
  sinecure: "闲职",
};

const macro = computed(() => scope.value === "world" || scope.value === "nation");

const region = ref(null);

function onScopeSelect(value) {
  manualScope.value = true;
  scope.value = value;
}

function backToAuto() {
  manualScope.value = false;
  scope.value = "region";
}

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

/** 按当前观察尺度拉聚合结果（宏观看势力，细尺度看道）。 */
async function loadView() {
  if (!branch.value) return;
  const data = await api.view(branch.value.id, scope.value);
  units.value = data.units;
}

/** 地图缩放驱动观察尺度；用户手动改过之后就不再自动跟随。 */
function onZoomChange(k) {
  if (manualScope.value) return;
  const next = k < 1.25 ? "world" : k < 2.2 ? "nation" : k < 4.5 ? "region" : "local";
  if (next !== scope.value) scope.value = next;
}

watch(scope, () => {
  loadView();
});

async function ensureBranch() {
  const list = await api.branches(WORLD);
  if (Array.isArray(list) && list.length) return list[0];
  return api.createBranch(WORLD, {
    precision: precision.value,
    seed: 1,
    name: "唐朝·主时间线",
  });
}

async function loadDecisions() {
  if (!branch.value) return;
  const before = decisions.value.length;
  decisions.value = await api.decisions(branch.value.id);
  relations.value = await api.relations(branch.value.id);
  // 有新的事找上门，就重新把浮层推到你面前
  if (decisions.value.length !== before) overlayDismissed.value = false;
}

async function loadCourt() {
  if (!branch.value) return;
  const id = branch.value.id;
  try {
    armies.value = await api.armies(id);
  } catch (err) {
    armies.value = { armies: [], tang_total: 0, yan_total: 0 };
  }
  try {
    loyalty.value = await api.loyalty(id);
  } catch (err) {
    loyalty.value = [];
  }
  try {
    historyStatus.value = await api.history(id);
  } catch (err) {
    historyStatus.value = { fired: [], diverged: [] };
  }
}

async function loadEnding() {
  if (!branch.value) return;
  try {
    ending.value = await api.ending(branch.value.id);
  } catch (err) {
    ending.value = null;
  }
}

async function boot() {
  try {
    scenario.value = (await api.world(WORLD)).scenario || null;
    branch.value = await ensureBranch();
    await loadState();
    await loadEvents();
    await loadView();
    await loadDecisions();
    await loadCourt();
    await loadEnding();
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
    lastReport.value = report;
    changes.value = report.changes || [];
    await loadState();
    await loadEvents();
    await loadDecisions();
    await loadCourt();
    await loadEnding();
    const bits = [`已推进 ${report.months} 个月（${report.from_date} → ${report.to_date}）`];
    if (report.event_count) bits.push(`新事件 ${report.event_count} 条`);
    if (report.decisions?.length) bits.push(`有 ${report.decisions.length} 件事等你决定`);
    message.value = bits.join("，") + "。";
  } catch (err) {
    message.value = `推进失败：${err.message}`;
  } finally {
    busy.value = false;
  }
}

async function onResolve(decision, option) {
  if (busy.value) return;
  busy.value = true;
  try {
    const result = await api.resolveDecision(branch.value.id, decision.id, option.key);
    message.value = `已决断：${decision.title} → ${option.label}`;
    decisionResult.value = {
      title: decision.title,
      option: option.label,
      applied: result.event?.metrics?.applied || [],
    };
    await loadState();
    await loadEvents();
    await loadDecisions();
    await loadCourt();
  } catch (err) {
    message.value = `决断失败：${err.message}`;
  } finally {
    busy.value = false;
    // 处理完一件，若有下一件，浮层应当自己再出现
    overlayDismissed.value = false;
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
        <p>安史之乱模拟器</p>
      </div>
    </div>
    <div v-if="branch" class="branch-meta">
      <nav class="view-tabs">
        <button :class="{ active: view === 'sim' }" @click="view = 'sim'">推演</button>
        <button :class="{ active: view === 'compare' }" @click="view = 'compare'">分支对比</button>
        <button :class="{ active: view === 'ai' }" @click="view = 'ai'">AI 分析</button>
      </nav>
      <span class="chip">时间 <b>{{ branch.current_date }}</b></span>
      <span class="chip">精度 <b>{{ PRECISIONS.find((p) => p.key === branch.precision)?.name }}</b></span>
      <span class="chip">已推进 <b>{{ branch.tick_index }}</b> 月</span>
    </div>
  </header>

  <main v-if="view === 'compare'" class="compare-main">
    <BranchCompare :world="WORLD" :current-branch-id="branch ? branch.id : null" />
  </main>

  <main v-else-if="view === 'ai'" class="compare-main">
    <AiPanel :branch-id="branch ? branch.id : null" :events="events" />
  </main>

  <main v-else class="stage">
    <section class="map-layer">
      <div class="map-toolbar">
        <div class="scale-group">
          <label for="scope">观察尺度</label>
          <select
            id="scope"
            :value="scope"
            @change="onScopeSelect($event.target.value)"
          >
            <option value="world">世界级</option>
            <option value="nation">国家级</option>
            <option value="region">地区级</option>
            <option value="local">局部级</option>
          </select>
          <span v-if="manualScope" class="auto-hint">
            手动模式
            <button class="link-btn" @click="backToAuto">恢复自动</button>
          </span>
          <span v-else class="auto-hint">跟随缩放自动切换</span>
        </div>
        <div class="legend">
          <span><i style="background:#5a7a96"></i>道界</span>
          <span><i style="background:rgba(214,62,42,.25)"></i>粮价偏高</span>
          <span><i style="background:rgba(214,62,42,.62)"></i>严重缺粮</span>
        </div>
      </div>
      <MapView
        :regions="regions"
        :selected="selected"
        :scale="scope"
        :factions="factions"
        :focus="spotlightRegion"
        @select="selectRegion"
        @zoom-change="onZoomChange"
      />
    </section>

    <!-- 顶部 HUD：只留最要紧的几项，其余收进侧栏 -->
    <header class="hud">
      <div class="hud-main">
        <span class="hud-date">{{ branch ? branch.current_date : "" }}</span>
        <span class="hud-role">{{ scenario ? scenario.role : "" }}</span>
      </div>
      <div class="hud-stats">
        <span v-if="tang">府库 <b>{{ Math.round(tang.treasury).toLocaleString() }}</b></span>
        <span v-if="allegiance">
          河北 <b>{{ allegiance.value.toFixed(2) }}</b> {{ allegiance.label }}
        </span>
        <span v-if="ending">结局 <b>{{ ending.grade }}</b></span>
      </div>
    </header>

    <aside class="side-panel" :class="{ open: drawerOpen }">
      <div v-if="ending" class="panel-block">
        <h2>五年之后</h2>
        <EndingCard :ending="ending" />
      </div>

      <div v-if="decisionResult" class="panel-block">
        <h2>刚才的决断</h2>
        <div class="result-card">
          <div class="r-title">{{ decisionResult.title }} → {{ decisionResult.option }}</div>
          <div v-if="!decisionResult.applied.length" class="r-empty">这次选择没有立刻改变可量化的指标。</div>
          <div v-for="item in decisionResult.applied" :key="item.label" class="r-row">
            <span class="r-label">{{ item.label }}</span>
            <span class="r-value">
              {{ Number(item.before).toLocaleString() }} →
              <b :class="item.after < item.before ? 'down' : item.after > item.before ? 'up' : ''">
                {{ Number(item.after).toLocaleString() }}
              </b>
              {{ item.unit }}
            </span>
          </div>
          <button class="link-btn" @click="decisionResult = null">收起</button>
        </div>
      </div>

      <div v-if="scenario" class="panel-block brief">
        <div class="brief-role">{{ scenario.role }}</div>
        <p class="brief-goal">{{ scenario.goal }}</p>
        <details class="brief-more">
          <summary>当前局面</summary>
          <p class="brief-text">{{ scenario.briefing }}</p>
          <ul class="brief-list">
            <li v-for="p in scenario.pressures" :key="p">{{ p }}</li>
          </ul>
        </details>
      </div>


      <div class="tab-strip">
        <button
          v-for="tab in [
            { key: 'decide', name: '决断', badge: decisions.length },
            { key: 'war', name: '军事', badge: 0 },
            { key: 'people', name: '人物', badge: 0 },
            { key: 'history', name: '史实', badge: historyStatus.diverged.length },
          ]"
          :key="tab.key"
          :class="{ active: panel === tab.key }"
          @click="panel = tab.key"
        >
          {{ tab.name }}
          <span v-if="tab.badge" class="count urgent">{{ tab.badge }}</span>
        </button>
      </div>

      <div v-show="panel === 'decide'" class="panel-block">
        <h2>
          待决事项
          <span v-if="decisions.length" class="count urgent">{{ decisions.length }}</span>
        </h2>
        <DecisionPanel
          :decisions="decisions"
          :relations="relations"
          :busy="busy"
          @resolve="onResolve"
        />
      </div>

      <div v-show="panel === 'war'" class="panel-block">
        <h2>各军</h2>
        <div class="army-totals">
          <span>唐军 {{ Math.round(armies.tang_total).toLocaleString() }}</span>
          <span>燕军 {{ Math.round(armies.yan_total).toLocaleString() }}</span>
        </div>
        <div v-for="a in armies.armies" :key="a.army_key" class="army">
          <div class="army-head">
            <span class="a-name">{{ a.name }}</span>
            <span class="a-power">{{ Math.round(a.power).toLocaleString() }}</span>
          </div>
          <div class="army-meta">
            {{ a.commander_name }} · 兵 {{ a.troops.toLocaleString() }}
          </div>
          <div class="army-bars">
            <span class="bar"><i :style="{ width: a.morale * 100 + '%' }"></i></span>
            <span class="bar-label">士气 {{ a.morale.toFixed(2) }}</span>
          </div>
          <div class="army-bars">
            <span class="bar supply"><i :style="{ width: a.supply * 100 + '%' }"></i></span>
            <span class="bar-label">补给 {{ a.supply.toFixed(2) }}</span>
          </div>
        </div>
      </div>

      <div v-show="panel === 'people'" class="panel-block">
        <h2>人物</h2>
        <div v-for="p in loyalty" :key="p.key" class="person" :class="p.status">
          <div class="p-head">
            <span class="p-name">{{ p.name }}</span>
            <span class="p-status">{{ p.status }}</span>
          </div>
          <div class="p-meta">
            {{ p.office || "无官职" }}（{{ RANK_LABELS[p.office_rank] || p.office_rank + " 品" }}·{{ KIND_LABELS[p.office_kind] || p.office_kind }}）
            · 统兵 {{ p.troops.toLocaleString() }}
          </div>
          <div class="p-bars">
            <span class="bar"><i :style="{ width: p.loyalty * 100 + '%' }"></i></span>
            <span class="bar-label">忠 {{ p.loyalty.toFixed(2) }}</span>
          </div>
        </div>
      </div>

      <div v-show="panel === 'history'" class="panel-block">
        <h2>史实对照</h2>
        <p class="hint">按史载发生的记为「应验」；因前提改变而没有发生的记为「改道」。</p>
        <div v-if="historyStatus.diverged.length" class="hist-group">
          <div class="hist-title">改道 {{ historyStatus.diverged.length }}</div>
          <div v-for="h in historyStatus.diverged" :key="h.key" class="hist-row diverged">
            <span class="h-title">{{ h.title }}</span>
            <span class="h-note">{{ h.date }} · {{ h.reason }}</span>
          </div>
        </div>
        <div class="hist-group">
          <div class="hist-title">应验 {{ historyStatus.fired.length }}</div>
          <div v-for="h in historyStatus.fired" :key="h.key" class="hist-row">
            <span class="h-title">{{ h.title }}</span>
            <span class="h-note">{{ h.date }}</span>
          </div>
        </div>
      </div>

      <div v-if="changes.length" class="panel-block">
        <h2>本期变化</h2>
        <div class="changes">
          <div v-for="c in changes" :key="c.region_key" class="change-row">
            <span class="c-name">{{ c.name }}</span>
            <span class="c-item" :class="c.price_delta > 0 ? 'up' : 'down'">
              粮价 {{ c.price_before.toFixed(2) }} → {{ c.price_after.toFixed(2) }}
            </span>
            <span v-if="Math.abs(c.unrest_delta) >= 0.01" class="c-item" :class="c.unrest_delta > 0 ? 'up' : 'down'">
              民变 {{ c.unrest_delta > 0 ? "+" : "" }}{{ c.unrest_delta.toFixed(2) }}
            </span>
          </div>
        </div>
      </div>

      <div class="panel-block">
        <h2>{{ macro ? "势力概览" : "地区详情" }}</h2>
        <div v-if="macro" class="unit-list">
          <div v-for="u in units" :key="u.key" class="unit">
            <div class="unit-name">{{ u.name }}</div>
            <div class="unit-meta">{{ u.metrics.region_count }} 道 · 人口 {{ Math.round(u.metrics.population).toLocaleString() }}</div>
            <div class="unit-row">
              <span>存粮 {{ Math.round(u.metrics.grain_stock).toLocaleString() }} 石</span>
              <span>粮价 {{ u.metrics.price_index.toFixed(2) }}</span>
            </div>
            <div class="unit-row">
              <span>民变峰值 {{ u.metrics.unrest_max.toFixed(2) }}</span>
              <span v-if="u.metrics.treasury != null">府库 {{ Math.round(u.metrics.treasury).toLocaleString() }}</span>
            </div>
          </div>
          <p class="hint">宏观视角按势力聚合，缩放地图可自动切换尺度。</p>
        </div>
        <RegionDetail v-else :region="region" @act="onAct" />
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

    <!-- 底部动作条：推进与进度，任何时刻都看得见 -->
    <footer class="action-bar">
      <div class="progress">
        <div class="progress-track"><i :style="{ width: progressPct + '%' }"></i></div>
        <span class="progress-label">
          距广德元年还有 {{ monthsLeft }} 月
        </span>
      </div>
      <div class="advance-group">
        <button class="advance" :disabled="busy" @click="advance(1)">1 月</button>
        <button class="advance" :disabled="busy" @click="advance(3)">3 月</button>
        <button class="advance primary" :disabled="busy" @click="advance(12)">1 年</button>
        <button
          class="sound-toggle"
          :class="{ off: muted }"
          :title="muted ? '开启音效' : '关闭音效'"
          @click="toggleSound"
        >
          {{ muted ? "静音" : "音效" }}
        </button>
        <button class="drawer-toggle" @click="drawerOpen = !drawerOpen">
          {{ drawerOpen ? "收起" : "朝局" }}
          <span v-if="decisions.length" class="count urgent">{{ decisions.length }}</span>
        </button>
      </div>
      <p class="action-hint">{{ message }}</p>
      <p v-if="error" class="action-hint error">{{ error }}</p>
    </footer>

    <!-- 决策：整屏只剩这一件事 -->
    <div v-if="showOverlay" class="decision-overlay">
      <div class="decision-sheet">
        <div class="sheet-head">
          <span>奏</span>
          <em>决断之后本月即结算</em>
        </div>
        <DecisionPanel
          :decisions="[activeDecision]"
          :relations="relations"
          :busy="busy"
          @resolve="onResolve"
        />
        <button class="link-btn sheet-later" @click="overlayDismissed = true">
          稍后再议
        </button>
      </div>
    </div>
  </main>
</template>