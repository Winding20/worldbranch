<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { api } from "../api.js";

const props = defineProps({
  world: { type: String, required: true },
  currentBranchId: { type: Number, default: null },
});

const branches = ref([]);
const leftId = ref(null);
const rightId = ref(null);
const data = ref(null);
const loading = ref(false);
const error = ref("");

const METRICS = [
  { key: "grain_stock", label: "存粮", unit: "石", digits: 0, invert: false },
  { key: "price_index", label: "粮价指数", unit: "", digits: 2, invert: true },
  { key: "unrest", label: "民变指数", unit: "", digits: 2, invert: true },
  { key: "tax_rate", label: "税率", unit: "", digits: 3, invert: false },
  { key: "population", label: "人口", unit: "人", digits: 0, invert: false },
];

const leftBranch = computed(() => branches.value.find((b) => b.id === leftId.value));
const rightBranch = computed(() => branches.value.find((b) => b.id === rightId.value));

async function loadBranches() {
  branches.value = await api.branches(props.world);
  if (!leftId.value && branches.value.length) leftId.value = branches.value[0].id;
  if (!rightId.value && branches.value.length > 1) rightId.value = branches.value[1].id;
  if (!rightId.value && branches.value.length === 1) rightId.value = branches.value[0].id;
}

async function loadCompare() {
  if (!leftId.value || !rightId.value) return;
  loading.value = true;
  error.value = "";
  try {
    data.value = await api.compare(leftId.value, rightId.value);
  } catch (err) {
    error.value = err.message;
    data.value = null;
  } finally {
    loading.value = false;
  }
}

async function forkCurrent() {
  if (!props.currentBranchId) return;
  const name = `分支 ${branches.value.length + 1}`;
  const created = await api.fork(props.currentBranchId, { name });
  await loadBranches();
  rightId.value = created.id;
  leftId.value = props.currentBranchId;
  await loadCompare();
}

function fmt(value, digits) {
  if (value == null) return "—";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function deltaClass(metric, delta) {
  if (!delta) return "";
  const good = metric.invert ? delta < 0 : delta > 0;
  return good ? "up" : "down";
}

function deltaText(metric, delta) {
  if (delta == null) return "—";
  if (delta === 0) return "持平";
  const sign = delta > 0 ? "+" : "";
  return sign + fmt(delta, metric.digits);
}

watch([leftId, rightId], loadCompare);
onMounted(async () => {
  await loadBranches();
  await loadCompare();
});
</script>

<template>
  <div class="compare">
    <div class="picker">
      <div class="pick">
        <label>分支 A</label>
        <select v-model="leftId">
          <option v-for="b in branches" :key="b.id" :value="b.id">
            #{{ b.id }} {{ b.name }}（{{ b.current_date }}）
          </option>
        </select>
      </div>
      <div class="vs">对比</div>
      <div class="pick">
        <label>分支 B</label>
        <select v-model="rightId">
          <option v-for="b in branches" :key="b.id" :value="b.id">
            #{{ b.id }} {{ b.name }}（{{ b.current_date }}）
          </option>
        </select>
      </div>
      <button class="fork-btn" @click="forkCurrent">从当前分支派生一条</button>
    </div>

    <div v-if="error" class="empty error">{{ error }}</div>
    <div v-else-if="loading" class="empty">正在对比…</div>

    <template v-else-if="data">
      <div v-if="data.divergence.same_branch" class="empty">
        选的是同一条分支，没有差异。派生一条新分支后再对比。
      </div>

      <div v-else class="summary">
        <div class="card">
          <div class="card-title">A · {{ data.left.name }}</div>
          <div class="card-meta">{{ data.left.current_date }} · 已推进 {{ data.left.tick_index }} 月 · {{ data.left.precision }}</div>
        </div>
        <div class="card">
          <div class="card-title">B · {{ data.right.name }}</div>
          <div class="card-meta">{{ data.right.current_date }} · 已推进 {{ data.right.tick_index }} 月 · {{ data.right.precision }}</div>
        </div>
        <div class="card wide">
          <div class="card-title">关系</div>
          <div class="card-meta">
            <span v-if="data.divergence.left_ancestor_of_right">B 从 A 派生而来</span>
            <span v-else-if="data.divergence.right_ancestor_of_left">A 从 B 派生而来</span>
            <span v-else>两条独立分支</span>
            <span v-if="data.divergence.common_ancestor_name">
              · 共同祖先：{{ data.divergence.common_ancestor_name }}
            </span>
            <span> · 共有事件 {{ data.events.common_count }} 条</span>
          </div>
        </div>
      </div>

      <h3 class="section">地区状态差异</h3>
      <table class="diff">
        <thead>
          <tr>
            <th>地区</th>
            <th v-for="m in METRICS" :key="m.key">{{ m.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in data.regions" :key="row.region_key">
            <td class="name">{{ row.name }}</td>
            <td v-for="m in METRICS" :key="m.key" class="metric">
              <span class="vals">
                {{ fmt(row.left[m.key], m.digits) }} → {{ fmt(row.right[m.key], m.digits) }}
              </span>
              <span class="delta" :class="deltaClass(m, row.delta[m.key])">
                {{ deltaText(m, row.delta[m.key]) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="events-cols">
        <div class="col">
          <h3 class="section">只在 A 发生（{{ data.events.left_only.length }}）</h3>
          <div v-if="!data.events.left_only.length" class="empty">无</div>
          <div v-for="e in data.events.left_only" :key="e.id" class="mini">
            <span class="date">{{ e.game_date }}</span>
            <span class="t">{{ e.title }}</span>
          </div>
        </div>
        <div class="col">
          <h3 class="section">只在 B 发生（{{ data.events.right_only.length }}）</h3>
          <div v-if="!data.events.right_only.length" class="empty">无</div>
          <div v-for="e in data.events.right_only" :key="e.id" class="mini">
            <span class="date">{{ e.game_date }}</span>
            <span class="t">{{ e.title }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.compare { padding: 14px 18px; overflow: auto; height: 100%; }

.picker {
  display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap;
  padding-bottom: 12px; border-bottom: 1px solid #2a3540; margin-bottom: 14px;
}
.pick { display: flex; flex-direction: column; gap: 4px; }
.pick label { font-size: 11px; color: #8fa1b0; }
.pick select {
  background: #1d262f; color: #dfe7ee; border: 1px solid #2a3540;
  border-radius: 8px; padding: 6px 10px; font-size: 12px; min-width: 230px;
}
.vs { font-size: 11px; color: #8fa1b0; padding-bottom: 8px; }
.fork-btn {
  margin-left: auto; padding: 7px 14px; border-radius: 8px;
  border: 1px solid #4aa8d8; background: rgba(74, 168, 216, 0.12);
  color: #4aa8d8; cursor: pointer; font-size: 12px;
}
.fork-btn:hover { background: rgba(74, 168, 216, 0.22); }

.summary { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.card {
  flex: 1; min-width: 200px; background: #161d24; border: 1px solid #2a3540;
  border-radius: 10px; padding: 10px 12px;
}
.card.wide { flex-basis: 100%; }
.card-title { font-size: 12.5px; margin-bottom: 3px; }
.card-meta { font-size: 11px; color: #8fa1b0; }

.section { font-size: 12px; color: #8fa1b0; margin: 16px 0 8px; font-weight: 600; }

.diff { width: 100%; border-collapse: collapse; font-size: 12px; }
.diff th {
  text-align: left; font-weight: 600; color: #8fa1b0; font-size: 11px;
  padding: 6px 8px; border-bottom: 1px solid #2a3540;
}
.diff td { padding: 6px 8px; border-bottom: 1px solid rgba(42, 53, 64, 0.5); }
.diff td.name { font-weight: 600; white-space: nowrap; }
.metric { display: flex; flex-direction: column; gap: 2px; }
.vals { color: #c6d6e2; font-size: 11.5px; }
.delta { font-size: 10.5px; color: #8fa1b0; }
.delta.up { color: #4ad89a; }
.delta.down { color: #d8614a; }

.events-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.mini {
  display: flex; gap: 8px; font-size: 11.5px; padding: 4px 0;
  border-bottom: 1px dashed rgba(42, 53, 64, 0.6);
}
.mini .date { color: #8fa1b0; font-size: 10.5px; white-space: nowrap; }
.empty { color: #8fa1b0; font-size: 12px; padding: 12px 0; }
.empty.error { color: #d8614a; }
</style>