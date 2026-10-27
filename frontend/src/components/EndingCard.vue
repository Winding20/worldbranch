<script setup>
defineProps({
  ending: { type: Object, default: null },
});
</script>

<template>
  <div v-if="ending" class="ending">
    <div class="e-head">
      <span class="e-grade">{{ ending.grade }}</span>
      <span class="e-score">{{ ending.score }} 分</span>
      <span class="e-date">{{ ending.date }} · 第 {{ ending.months }} 个月</span>
    </div>
    <p class="e-verdict">{{ ending.verdict }}</p>

    <div class="e-bars">
      <div v-for="(value, key) in ending.scores" :key="key" class="e-bar">
        <span class="b-label">{{ key }}</span>
        <span class="b-track"><i :style="{ width: value + '%' }"></i></span>
        <span class="b-value">{{ value }}</span>
      </div>
    </div>

    <div class="e-metrics">
      <span>府库 {{ Number(ending.metrics.treasury).toLocaleString() }} 贯</span>
      <span>藩镇臣属度 {{ ending.metrics.allegiance.toFixed(2) }}</span>
      <span>决策 {{ ending.metrics.decisions_made }} 次</span>
      <span>事件 {{ ending.metrics.events }} 条</span>
    </div>
  </div>
</template>

<style scoped>
.ending {
  border: 1px solid rgba(216, 162, 74, 0.6);
  background: linear-gradient(180deg, rgba(216, 162, 74, 0.14), transparent);
  border-radius: 10px;
  padding: 12px 13px;
}
.e-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.e-grade { font-size: 20px; font-weight: 700; color: #f0d6a8; letter-spacing: 2px; }
.e-score { font-size: 12px; color: #d8a24a; }
.e-date { margin-left: auto; font-size: 10.5px; color: #8fa1b0; }
.e-verdict { margin: 0 0 10px; font-size: 12px; line-height: 1.7; color: #dfe7ee; }

.e-bars { display: flex; flex-direction: column; gap: 5px; margin-bottom: 10px; }
.e-bar { display: flex; align-items: center; gap: 8px; font-size: 10.5px; color: #8fa1b0; }
.b-label { width: 30px; }
.b-track { flex: 1; height: 5px; background: #1d262f; border-radius: 3px; overflow: hidden; }
.b-track i { display: block; height: 100%; background: linear-gradient(90deg, #4aa8d8, #d8a24a); }
.b-value { width: 30px; text-align: right; color: #c6d6e2; }

.e-metrics { display: flex; flex-wrap: wrap; gap: 10px; font-size: 10.5px; color: #8fa1b0; }
</style>