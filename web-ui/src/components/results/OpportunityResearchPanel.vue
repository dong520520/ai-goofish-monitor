<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { radarApi, type Category, type MarketEvidence } from '@/api/opportunities'
import { Button } from '@/components/ui/button'

const props = defineProps<{ categories: Category[]; revision: number }>()
const emit = defineEmits<{ inspect: [category: string, keyword: string, scope: string] }>()
const category = ref(''), keyword = ref(''), scope = ref('demo'), busy = ref(false), error = ref('')
const evidence = ref<MarketEvidence | null>(null)
const budget = ref(20), breadth = ref(40), message = ref('')
let sequence = 0
async function load() {
  const request = ++sequence
  busy.value = true; error.value = ''
  try {
    const result = await radarApi.research(category.value, keyword.value, scope.value)
    if (request === sequence) evidence.value = result
  } catch (e) { if (request === sequence) error.value = (e as Error).message }
  finally { if (request === sequence) busy.value = false }
}
async function discover() {
  busy.value = true; error.value = ''; message.value = ''
  try {
    await radarApi.expand()
    const plan = await radarApi.plan(budget.value, breadth.value / 100)
    message.value = `发现待办 ${plan.jobs.length} 条，覆盖 ${plan.category_coverage.length} 个类目；相同计划重复提交不会追加任务。仅人工待办。`
    await load()
  } catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}
watch(() => props.revision, load)
onMounted(load)
const number = (v: string | number | null) => v === null ? '未知' : v
</script>

<template>
  <section class="space-y-4 rounded-xl border border-teal-200 bg-white p-5">
    <div><h2 class="text-xl font-bold text-slate-900">全类目发现与市场证据</h2><p class="mt-1 text-xs leading-5 text-slate-500">沿用四策略六维评分。市场分析按来源、币种、成色及明确型号/规格分组；报价和兴趣信号供人工验证。</p></div>
    <form class="grid items-end gap-3 sm:grid-cols-3 lg:grid-cols-5" @submit.prevent="load">
      <label class="research-field">类目<select v-model="category"><option value="">全部类目</option><option v-for="c in categories" :key="c.name">{{ c.name }}</option></select></label>
      <label class="research-field">关键词<input v-model="keyword" maxlength="200" placeholder="例如：键盘" /></label>
      <label class="research-field">证据来源<select v-model="scope"><option value="demo">合成演示</option><option value="imported">真实导入观测</option><option value="all">全部（分别分析）</option></select></label>
      <Button :disabled="busy" type="submit">分析竞品样本</Button>
      <a :href="radarApi.researchExportUrl(category, keyword, scope)" class="text-sm font-semibold text-teal-700">导出证据 CSV</a>
    </form>
    <div class="flex flex-wrap items-end gap-3 rounded-lg bg-slate-50 p-3">
      <label class="research-field">发现预算（1–50）<input v-model.number="budget" type="number" min="1" max="50" /></label>
      <label class="research-field">广度占比（%）<input v-model.number="breadth" type="number" min="0" max="100" /></label>
      <Button variant="outline" :disabled="busy" @click="discover">扩词并公平规划类目</Button>
      <p class="text-xs text-slate-500">广度探索 / 细分深挖 · 无联网采集</p>
    </div>
    <p v-if="message" role="status" class="text-sm text-teal-800">{{ message }}</p>
    <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
    <template v-if="evidence">
      <div class="flex max-h-28 flex-wrap gap-2 overflow-y-auto" aria-label="类目覆盖"><span v-for="c in evidence.category_coverage" :key="c.category" class="rounded border px-2 py-1 text-xs" :class="c.sample_count ? 'border-teal-200 bg-teal-50 text-teal-800' : 'text-slate-400'">{{ c.category }} {{ c.sample_count }} 件</span></div>
      <div class="overflow-x-auto"><table class="w-full min-w-[780px] text-left text-sm"><thead class="border-b text-xs text-slate-500"><tr><th class="p-2">竞品分组</th><th class="p-2">样本 / 卖家</th><th class="p-2">报价 P25 / P50 / P75</th><th class="p-2">兴趣覆盖</th><th class="p-2">可信度 / 下一步</th></tr></thead>
        <tbody><tr v-for="(c, i) in evidence.cohorts" :key="i" class="border-b align-top"><td class="p-2"><strong>{{ c.category }}</strong><p class="mt-1 text-xs text-slate-500">{{ c.source }} · {{ c.currency }} · {{ c.condition || '成色未知' }}<br />{{ c.model || c.sku || c.specification || '型号规格未确认' }}</p><span v-if="c.is_demo" class="text-xs text-amber-700">合成样例</span></td><td class="p-2">{{ c.sample_count }} / {{ number(c.distinct_sellers) }}<p class="text-xs text-slate-500">有报价 {{ c.priced_count }} 件</p></td><td class="p-2 tabular-nums">{{ number(c.p25) }} / {{ number(c.p50) }} / {{ number(c.p75) }}<p class="mt-1 text-xs text-slate-500">{{ c.currency }} · 观测报价分布</p></td><td class="p-2 text-xs">想要 {{ Math.round(c.want_coverage * 100) }}%<br />浏览 {{ Math.round(c.view_coverage * 100) }}%</td><td class="max-w-60 p-2"><strong>{{ c.confidence_score }} / 100</strong><p v-for="m in c.missing" :key="m" class="text-xs leading-5 text-amber-800">{{ m }}</p><button class="mt-2 text-xs font-semibold text-teal-700 underline" @click="emit('inspect', c.category, keyword, c.is_demo ? 'demo' : 'imported')">查看评分与候选</button></td></tr><tr v-if="!evidence.cohorts.length"><td colspan="5" class="p-6 text-center text-slate-500">暂无样本。载入合成演示，或导入已获许可的 CSV。</td></tr></tbody>
      </table></div>
      <p class="text-xs text-slate-500">{{ evidence.note }} <span v-if="evidence.truncated">仅展示前100组，请按类目或关键词筛选。</span></p>
      <details v-if="evidence.lineage.length" class="text-xs text-slate-600"><summary class="cursor-pointer font-semibold">关键词 → 观测商品证据链</summary><p v-for="k in evidence.lineage" :key="k.id" class="mt-2 break-words">{{ k.category }} / {{ k.keyword }} · {{ k.origin }} → {{ k.matched_count }} 件，商品 #{{ k.item_ids.join('、#') }}</p></details>
    </template>
  </section>
</template>

<style scoped>
.research-field { display: flex; flex-direction: column; gap: .35rem; font-size: .75rem; color: #475569; }
.research-field input, .research-field select { min-width: 0; width: 100%; border: 1px solid #cbd5e1; border-radius: .5rem; padding: .5rem; color: #0f172a; background: white; }
</style>
