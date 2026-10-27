<script setup>
import { computed, ref } from "vue";
import { api } from "../api.js";

const props = defineProps({
  branchId: { type: Number, default: null },
  events: { type: Array, default: () => [] },
  scope: { type: String, default: "region" },
});
const emit = defineEmits(["select-region"]);

const SCOPE_ORDER = { local: 1, region: 2, nation: 3, world: 4 };
const KIND_LABEL = {
  harvest_shock: "农事灾害",
  famine: "粮荒",
  price_spike: "粮价",
  unrest: "民变",
  grain_flow: "调运",
  price_pressure: "外溢",
  fiscal_crisis: "财政",
  regional_crisis: "区域危机",
  local_disturbance: "地方",
  user_shock: "干预",
  user_relief: "干预",
  user_tax: "干预",
};

const expanded = ref(new Set());
const chains = ref({});
const loading = ref(new Set());

const visible = computed(() => {
  const threshold = SCOPE_ORDER[props.scope] || 1;
  return props.events.filter((e) => (SCOPE_ORDER[e.scope] || 1) >= threshold);
});

function hasCause(e) {
  return (e.causes || []).some((c) => c && c.event_id);
}

function isExpanded(id) {
  return expanded.value.has(id);
}

async function toggle(event) {
  const id = event.id;
  const next = new Set(expanded.value);
  if (next.has(id)) {
    next.delete(id);
    expanded.value = next;
    return;
  }
  next.add(id);
  expanded.value = next;

  if (chains.value[id]) return;
  loading.value = new Set(loading.value).add(id);
  try {
    const chain = await api.chain(props.branchId, id);
    chains.value = {
      ...chains.value,
      [id]: chain.nodes.filter((n) => n.id !== id),
    };
  } catch (err) {
    chains.value = { ...chains.value, [id]: [] };
  } finally {
    const done = new Set(loading.value);
    done.delete(id);
    loading.value = done;
  }
}

function parentsOf(id) {
  return [...(chains.value[id] || [])].sort((a, b) =>
    a.game_date < b.game_date ? -1 : a.game_date > b.game_date ? 1 : a.id - b.id
  );
}

function onCard(event) {
  if (event.region_keys && event.region_keys.length) {
    emit("select-region", event.region_keys[0]);
  }
  toggle(event);
}
</script>

<template>
  <div class="event-list">
    <div v-if="!visible.length" class="empty">当前尺度下暂无事件，推进模拟试试。</div>

    <div
      v-for="e in visible"
      :key="e.id"
      class="event-item"
      :class="{ expanded: isExpanded(e.id) }"
    >
      <div class="row1">
        <span class="date">{{ e.game_date }}</span>
        <span class="scope-tag" :class="e.scope">
          {{ { local: "局部", region: "地区", nation: "国家", world: "世界" }[e.scope] || e.scope }}
        </span>
        <span class="kind-tag">{{ KIND_LABEL[e.kind] || e.kind }}</span>
        <span v-if="hasCause(e)" class="cause-flag">因果</span>
        <span class="severity-dots">
          <i v-for="i in 5" :key="i" :class="{ on: i <= e.severity }"></i>
        </span>
      </div>

      <div class="title" @click="onCard(e)">{{ e.title }}</div>
      <div class="summary" @click="onCard(e)">{{ e.summary }}</div>

      <div v-if="isExpanded(e.id)" class="chain">
        <div v-if="loading.has(e.id)" class="chain-empty">正在追溯因果…</div>
        <template v-else-if="parentsOf(e.id).length">
          <div class="chain-title">因果链（由远及近）</div>
          <div v-for="p in parentsOf(e.id)" :key="p.id" class="chain-node">
            <span class="chain-date">{{ p.game_date }}</span>
            <span class="scope-tag" :class="p.scope">
              {{ { local: "局部", region: "地区", nation: "国家", world: "世界" }[p.scope] || p.scope }}
            </span>
            <span class="chain-text">{{ p.title }}</span>
          </div>
          <div class="chain-arrow">↓ 最终导致</div>
        </template>
        <div v-else class="chain-empty">该事件由规则直接产生，没有上游事件。</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.event-list { display: flex; flex-direction: column; gap: 7px; overflow: auto; flex: 1; }
.empty { color: #8fa1b0; font-size: 12px; padding: 12px 0; }

.event-item {
  border: 1px solid #2a3540;
  border-radius: 9px;
  padding: 8px 10px;
  background: #1d262f;
  cursor: pointer;
}
.event-item:hover { border-color: #3d5163; }
.event-item.expanded { border-color: #d8a24a; }

.row1 { display: flex; align-items: center; gap: 7px; margin-bottom: 3px; }
.date { font-size: 10.5px; color: #8fa1b0; }
.scope-tag {
  font-size: 10px; padding: 1px 6px; border-radius: 5px;
  background: rgba(74, 168, 216, 0.14); color: #4aa8d8;
}
.scope-tag.world { background: rgba(216, 97, 74, 0.16); color: #d8614a; }
.scope-tag.nation { background: rgba(216, 162, 74, 0.16); color: #d8a24a; }
.scope-tag.local { background: rgba(74, 216, 154, 0.14); color: #4ad89a; }
.kind-tag {
  font-size: 10px; padding: 1px 6px; border-radius: 5px;
  background: rgba(143, 161, 176, 0.14); color: #8fa1b0;
}
.cause-flag {
  font-size: 10px; padding: 1px 6px; border-radius: 5px;
  background: rgba(216, 162, 74, 0.18); color: #d8a24a;
}
.severity-dots { margin-left: auto; display: flex; gap: 2px; }
.severity-dots i { width: 5px; height: 5px; border-radius: 50%; background: #34424f; }
.severity-dots i.on { background: #d8614a; }

.title { font-size: 12.5px; margin-bottom: 2px; }
.summary { font-size: 11px; color: #8fa1b0; line-height: 1.5; }

.chain { margin-top: 8px; }
.chain-title { font-size: 10.5px; color: #d8a24a; margin: 0 0 5px; letter-spacing: 0.4px; }
.chain-node {
  display: flex; align-items: center; gap: 6px; font-size: 11px;
  padding: 3px 0 3px 10px;
  border-left: 2px solid rgba(216, 162, 74, 0.35);
  margin-bottom: 2px;
}
.chain-date { color: #8fa1b0; font-size: 10.5px; white-space: nowrap; }
.chain-text { color: #dfe7ee; }
.chain-arrow { font-size: 10px; color: #d8a24a; padding-left: 10px; margin-top: 3px; }
.chain-empty { font-size: 10.5px; color: #8fa1b0; padding: 6px 0 2px; }
</style>