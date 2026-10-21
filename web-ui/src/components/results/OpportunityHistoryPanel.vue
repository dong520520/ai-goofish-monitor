<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { radarApi, type ObservationHistory } from '@/api/opportunities'
import { Button } from '@/components/ui/button'
const props = defineProps<{ itemId: number }>()
const history = ref<ObservationHistory | null>(null), error = ref(''), loading = ref(false)
let sequence = 0
async function load() {
  const current = ++sequence
  loading.value = true; error.value = ''
  try { const result = await radarApi.history(props.itemId); if (current === sequence) history.value = result }
  catch (e) { if (current === sequence) error.value = (e as Error).message }
  finally { if (current === sequence) loading.value = false }
}
watch(() => props.itemId, () => { history.value = null; void load() }, { immediate: true })
const segments = computed(() => {
  const points = history.value?.points ?? []
  const values = points.flatMap(p => p.price === null ? [] : [Number(p.price)])
  if (values.length < 2) return []
  const low = Math.min(...values), range = Math.max(...values) - low || 1
  const lines: string[] = []; let current: string[] = []
  points.forEach((p, index) => {
    if (p.price === null) { if (current.length > 1) lines.push(current.join(' ')); current = []; return }
    current.push(`${8 + 284 * index / Math.max(1, points.length - 1)},${88 - 72 * (Number(p.price) - low) / range}`)
  })
  if (current.length > 1) lines.push(current.join(' '))
  return lines
})
function delta(value: number | null | undefined) { return value == null ? '待观察' : (value > 0 ? '+' : '') + value }
</script>
<template>
  <section class="min-w-0 space-y-3 rounded-xl border border-teal-100 bg-teal-50/30 p-4" aria-label="持续观测证据">
    <div class="flex flex-wrap items-center justify-between gap-2"><h3 class="font-bold">持续观测证据</h3><Button variant="outline" size="sm" :disabled="loading" @click="load">刷新观测</Button></div>
    <p v-if="error" role="alert" class="text-red-700">{{ error }}</p>
    <template v-if="history">
      <p class="text-xs leading-5 text-slate-600">窗口内 {{ history.distinct_times }} 个观察时点 / 全部 {{ history.total_observations }} 条快照。{{ history.baseline_only ? '目前只有观察基线，尚不能计算变化。' : `窗口首末报价差：${delta(history.price_delta)}；请结合规格与成色核验。` }}</p>
      <svg v-if="segments.length" viewBox="0 0 300 100" class="h-28 w-full rounded bg-white" role="img" aria-label="已观察报价变化，按观察时点等距排列；缺失报价不连线">
        <line x1="8" y1="90" x2="292" y2="90" stroke="#cbd5e1" />
        <polyline v-for="(line, i) in segments" :key="i" :points="line" fill="none" stroke="#0f766e" stroke-width="2" />
      </svg>
      <p v-if="segments.length" class="text-[11px] text-slate-500">横轴按观察时点等距排列；不代表成交或每日连续采样。</p>
      <div class="max-h-64 w-full min-w-0 overflow-auto"><table class="w-full min-w-[560px] text-left text-xs"><thead><tr class="border-b text-slate-500"><th class="py-2">观察时间</th><th>报价 / 差值</th><th>想要 / 差值</th><th>浏览 / 差值</th></tr></thead><tbody><template v-for="p in [...history.points].reverse()" :key="p.observation_id"><tr class="border-b"><td class="py-3">{{ new Date(p.observed_at).toLocaleString('zh-CN') }}</td><td>{{ p.price ?? '未知' }} {{ p.currency }} / {{ delta(p.changes.price) }}</td><td>{{ p.want_count ?? '未知' }} / {{ delta(p.changes.want_count) }}</td><td>{{ p.view_count ?? '未知' }} / {{ delta(p.changes.view_count) }}</td></tr><tr v-if="p.warnings.length"><td colspan="4" class="pb-2 text-amber-800">{{ p.warnings.join('；') }}</td></tr></template></tbody></table></div>
      <p class="text-xs leading-5 text-slate-500">{{ history.note }}{{ history.truncated ? ' 当前仅展示最近100条快照。' : '' }}</p>
    </template>
  </section>
</template>
