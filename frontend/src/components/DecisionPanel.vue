<script setup>
import { computed } from "vue";

const props = defineProps({
  decisions: { type: Array, default: () => [] },
  relations: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(["resolve"]);

const allegiance = computed(() =>
  props.relations.find((r) => r.from_key === "fanzhen")
);

function relationClass(value) {
  if (value >= 0.35) return "ok";
  if (value >= 0.2) return "warn";
  return "danger";
}

//: 多数朝臣主张的那一项，在选项上加一圈高亮——但只是个提示，不是推荐。
function isFavored(decision, option) {
  const advice = decision.advice || [];
  if (advice.length < 2) return false;
  const count = advice.filter((a) => a.option_key === option.key).length;
  return count * 2 > advice.length;
}
</script>

<template>
  <div class="decision-panel">
    <div v-if="allegiance" class="relation">
      <span class="rel-label">河北藩镇臣属度</span>
      <span class="rel-value" :class="relationClass(allegiance.value)">
        {{ allegiance.value.toFixed(2) }} · {{ allegiance.label }}
      </span>
    </div>

    <div v-if="!decisions.length" class="no-decision">
      暂无待决事项。推进时间，事情会找上门来。
    </div>

    <div v-for="d in decisions" :key="d.id" class="decision-card">
      <div class="d-head">
        <span class="d-date">{{ d.game_date }}</span>
        <span class="d-title">{{ d.title }}</span>
      </div>
      <p class="d-desc">{{ d.description }}</p>

      <div v-if="d.advice && d.advice.length" class="d-advice">
        <div class="adv-head">
          朝议
          <span v-if="d.advice_consensus" class="adv-consensus">一致</span>
          <span v-else class="adv-split">分歧</span>
        </div>
        <div v-for="a in d.advice" :key="a.character_key" class="adv-row">
          <span class="adv-who">{{ a.name }}<i>{{ a.office }}</i></span>
          <span class="adv-say">「{{ a.text }}」</span>
          <span class="adv-meta">
            主{{ a.option_label }}
            <b v-if="a.tag">· {{ a.tag }}</b>
            <em>才略 {{ a.ability }} 忠诚 {{ a.loyalty }}</em>
          </span>
        </div>
      </div>

      <div class="d-options">
        <button
          v-for="opt in d.options"
          :key="opt.key"
          class="d-option"
          :class="{ favored: isFavored(d, opt) }"
          :disabled="busy"
          @click="emit('resolve', d, opt)"
        >
          <span class="opt-label">{{ opt.label }}</span>
          <span class="opt-detail">{{ opt.detail }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.decision-panel { display: flex; flex-direction: column; gap: 10px; }

/* ---------------------------------- 朝议 ---------------------------------- */
.d-advice {
  border-left: 2px solid #3a4a58;
  padding: 6px 0 6px 10px;
  margin: 0 0 10px;
}
.adv-head {
  font-size: 10.5px;
  color: #8fa1b0;
  letter-spacing: 2px;
  margin-bottom: 6px;
}
.adv-consensus { color: #4ad89a; margin-left: 8px; letter-spacing: 0; }
.adv-split { color: #d8a24a; margin-left: 8px; letter-spacing: 0; }
.adv-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 5px 0;
  border-bottom: 1px dashed rgba(42, 53, 64, 0.55);
}
.adv-row:last-child { border-bottom: none; }
.adv-who { font-size: 12px; color: #dfe7ee; }
.adv-who i { font-style: normal; font-size: 10px; color: #8fa1b0; margin-left: 6px; }
.adv-say { font-size: 11.5px; color: #c6d6e2; line-height: 1.6; }
.adv-meta { font-size: 10px; color: #8fa1b0; }
.adv-meta b { color: #c98f5a; font-weight: 500; }
.adv-meta em { font-style: normal; float: right; opacity: 0.75; }
.d-option.favored { border-color: rgba(216, 162, 74, 0.45); }

.relation {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 11.5px; padding: 6px 10px; border-radius: 8px;
  background: #1d262f; border: 1px solid #2a3540;
}
.rel-label { color: #8fa1b0; }
.rel-value { font-weight: 600; }
.rel-value.ok { color: #4ad89a; }
.rel-value.warn { color: #d8a24a; }
.rel-value.danger { color: #d8614a; }

.no-decision {
  font-size: 11.5px; color: #8fa1b0; padding: 10px 12px;
  border: 1px dashed #2a3540; border-radius: 9px; line-height: 1.6;
}

.decision-card {
  border: 1px solid rgba(216, 162, 74, 0.55);
  background: linear-gradient(180deg, rgba(216, 162, 74, 0.08), transparent);
  border-radius: 10px;
  padding: 11px 12px;
}
.d-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.d-date { font-size: 10.5px; color: #8fa1b0; }
.d-title { font-size: 13.5px; font-weight: 600; color: #f0d6a8; }
.d-desc { margin: 0 0 10px; font-size: 11.5px; line-height: 1.65; color: #c6d6e2; }

.d-options { display: flex; flex-direction: column; gap: 6px; }
.d-option {
  display: flex; flex-direction: column; gap: 2px;
  text-align: left; padding: 8px 10px; border-radius: 8px;
  border: 1px solid #2a3540; background: #1d262f; cursor: pointer;
}
.d-option:hover:not(:disabled) { border-color: #d8a24a; background: rgba(216, 162, 74, 0.08); }
.d-option:disabled { opacity: 0.5; cursor: progress; }
.opt-label { font-size: 12.5px; color: #dfe7ee; font-weight: 600; }
.opt-detail { font-size: 10.5px; color: #8fa1b0; line-height: 1.5; }
</style>