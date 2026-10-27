<script setup>
import { computed } from "vue";

const props = defineProps({
  region: { type: Object, default: null },
});
const emit = defineEmits(["act"]);

const QUALITY_LABEL = {
  estimate: "估算",
  assumption: "假设",
  unknown: "未知",
  approximate: "近似",
};

const monthly = computed(() =>
  props.region ? props.region.population * 0.42 : 0
);

function tag(field) {
  const v = (props.region?.data_quality || {})[field];
  return v ? QUALITY_LABEL[v] || v : "";
}

function doAct(kind) {
  if (!props.region) return;
  emit("act", kind, props.region);
}
</script>

<template>
  <div v-if="!region" class="empty">点击地图上的地区</div>
  <div v-else>
    <div class="kv"><span>名称</span><b>{{ region.name }}</b></div>
    <div class="kv">
      <span>人口</span>
      <b>{{ Number(region.population).toLocaleString() }}<em v-if="tag('population')">{{ tag("population") }}</em></b>
    </div>
    <div class="kv"><span>存粮</span><b>{{ Math.round(region.grain_stock).toLocaleString() }} 石</b></div>
    <div class="kv"><span>可支撑</span><b>{{ (region.grain_stock / (monthly || 1)).toFixed(1) }} 个月</b></div>
    <div class="kv"><span>粮价指数</span><b>{{ (region.price_index || 1).toFixed(2) }}</b></div>
    <div class="kv"><span>民变指数</span><b>{{ (region.unrest || 0).toFixed(2) }}</b></div>
    <div class="kv"><span>税率</span><b>{{ ((region.tax_rate || 0) * 100).toFixed(0) }}%</b></div>
    <div class="kv"><span>所属势力</span><b>{{ region.faction_key || "—" }}</b></div>

    <div class="actions">
      <button class="act act-danger" @click="doAct('shock')">制造歉收</button>
      <button class="act" @click="doAct('relief')">开仓赈济</button>
      <button class="act" @click="doAct('tax-down')">减税 2%</button>
      <button class="act" @click="doAct('tax-up')">加税 2%</button>
    </div>
    <p class="hint">干预会写进事件流，并成为后续粮荒、调运的因果起点。</p>
  </div>
</template>

<style scoped>
.empty { color: #8fa1b0; font-size: 12px; padding: 12px 0; }
.kv {
  display: flex; justify-content: space-between; padding: 5px 0;
  border-bottom: 1px dashed rgba(42, 53, 64, 0.7); font-size: 12px;
}
.kv:last-of-type { border-bottom: none; }
.kv span:first-child { color: #8fa1b0; }
.kv b { font-weight: 600; }
.kv em {
  font-style: normal; font-size: 10px; padding: 1px 6px; border-radius: 5px;
  background: rgba(216, 162, 74, 0.15); color: #d8a24a; margin-left: 6px;
}
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; margin-top: 10px; }
.act {
  padding: 6px 4px; font-size: 11px; border-radius: 7px;
  border: 1px solid #2a3540; background: #1d262f; color: #dfe7ee; cursor: pointer;
}
.act:hover { border-color: #4aa8d8; color: #4aa8d8; }
.act-danger:hover { border-color: #d8614a; color: #d8614a; }
.hint { font-size: 10.5px; color: #8fa1b0; margin: 8px 0 0; line-height: 1.5; }
</style>