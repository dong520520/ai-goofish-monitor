<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Radar, Upload, Download, SlidersHorizontal, ArrowUpRight, FlaskConical } from 'lucide-vue-next'
import { radarApi, type Category, type ImportReport, type Keyword, type Opportunity, type RadarFilters, type Strategy } from '@/api/opportunities'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import OpportunityHistoryPanel from '@/components/results/OpportunityHistoryPanel.vue'
import OpportunityMonitorPanel from '@/components/results/OpportunityMonitorPanel.vue'
import OpportunityResearchPanel from '@/components/results/OpportunityResearchPanel.vue'
import OpportunityBusinessPanel from '@/components/results/OpportunityBusinessPanel.vue'
import OpportunityImportDialog from '@/components/results/OpportunityImportDialog.vue'

const modes: { key: Strategy; label: string; note: string }[] = [
  { key: 'physical', label: '实物选品', note: '采购、运费、履约与售后' },
  { key: 'virtual', label: '合规虚拟', note: '原创权利、平台可售与数字交付' },
  { key: 'resale', label: '低买高卖', note: '转售依据、成色真实性与流动性' },
  { key: 'blue_ocean', label: '蓝海探索', note: '长尾需求与竞争样本，优先验证' },
]
const dimensionLabels: Record<string, string> = { demand: '市场需求', profit: '预计利润', competition: '竞争友好度', fulfillment: '履约可行性', risk: '风险可控', differentiation: '差异化' }
const costLabels: Record<string, string> = { expected_sale_price: '预计成交价', purchase_cost: '采购成本', shipping_cost: '运费', platform_fee: '平台费用', fulfillment_cost: '履约成本', expected_loss: '预计损耗', resale_reference: '转售参考价' }
const evidenceLabels: Record<string, string> = { evidence_note: '成本假设依据', supplier_evidence: '货源 / 取得方式依据', delivery_evidence: '交付能力依据', rights_evidence: '权利授权依据', platform_evidence: '平台可售性依据', resale_evidence: '转售参考价依据', authenticity_evidence: '真实性 / 成色依据', differentiation_evidence: '差异化依据' }
const filters = reactive<RadarFilters>({ strategy: 'physical', category: '', q: '', min_confidence: 0, source_scope: 'all', sort: 'score_total', pool: 'all' })
const poolLabels: Record<string, string> = { candidate: '候选待验证', running: '七天测试中', completed: '已完成测试', stopped: '已停止测试' }
const importOpen = ref(false), researchScope = ref<string | undefined>(undefined)
const items = ref<Opportunity[]>([]), categories = ref<Category[]>([]), keywords = ref<Keyword[]>([])
const total = ref(0), page = ref(1), busy = ref(false), loading = ref(false), error = ref(''), message = ref('')
const report = ref<ImportReport | null>(null), selected = ref<Opportunity | null>(null)
const researchRevision = ref(0)
const businessRevision = ref(0)
const detailOpen = ref(false), configOpen = ref(false), costDraft = ref<Record<string, string | null>>({})
const config = reactive<Category>({ name: '', parent: null, keywords: [] })
const seedText = ref(''), breadth = ref(40), budget = ref(10), queueSize = ref(0)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / 20)))
const knownMargin = computed(() => items.value.filter(item => item.score.profit.net_margin !== null).length)
const demoCount = computed(() => items.value.filter(item => item.score.is_demo).length)
let requestNumber = 0

async function load(reset = false) {
  if (reset) page.value = 1
  const request = ++requestNumber
  loading.value = true
  error.value = ''
  try {
    const data = await radarApi.list({ ...filters }, page.value)
    if (request === requestNumber) { items.value = data.items; total.value = data.total }
  } catch (e) { if (request === requestNumber) error.value = (e as Error).message }
  finally { if (request === requestNumber) loading.value = false }
}
async function act(action: () => Promise<unknown>) {
  busy.value = true; error.value = ''; message.value = ''
  try { await action() } catch (e) { error.value = (e as Error).message } finally { busy.value = false }
}
async function imported(action: () => Promise<ImportReport>, scope?: string) {
  await act(async () => { report.value = await action(); if (scope) researchScope.value = scope; researchRevision.value++; await load(true) })
}
async function importedFile(result: ImportReport, scope: string) {
  report.value = result; filters.source_scope = scope; filters.pool = 'all'; filters.category = ''; filters.q = ''
  filters.min_confidence = 0; filters.min_margin = undefined
  researchScope.value = scope; researchRevision.value++
  await load(true)
}
async function openItem(item: { id: number }) {
  await act(async () => {
    selected.value = await radarApi.detail(item.id, filters.strategy)
    costDraft.value = { ...selected.value.costs }
    detailOpen.value = true
  })
}
async function saveCosts() {
  if (!selected.value) return
  await act(async () => {
    const payload = Object.fromEntries(Object.entries(costDraft.value).map(([key, value]) => [key, key in costLabels && (value === '' || value == null) ? null : value]))
    await radarApi.costs(selected.value!.id, payload)
    selected.value = await radarApi.detail(selected.value!.id, filters.strategy)
    businessRevision.value++
    await load()
    message.value = '假设已保存，四种策略评分已更新'
  })
}
async function addCandidate() {
  if (!selected.value) return
  await act(async () => {
    await radarApi.candidate(selected.value!.id, filters.strategy)
    selected.value = await radarApi.detail(selected.value!.id, filters.strategy)
    message.value = '候选已保存，原有实验状态保留'
    await load()
  })
}
async function refreshSelected() {
  if (!selected.value) return
  selected.value = await radarApi.detail(selected.value.id, filters.strategy)
  costDraft.value = { ...selected.value.costs }
  await load()
}
function editCategory(event: Event) {
  const found = categories.value.find(c => c.name === (event.target as HTMLSelectElement).value)
  Object.assign(config, found ? { ...found, keywords: [...found.keywords] } : { name: '', parent: null, keywords: [] })
  seedText.value = config.keywords.join('，')
}
async function saveCategory() {
  await act(async () => {
    categories.value = await radarApi.saveCategory({ ...config, keywords: seedText.value.split(/[,，\n]/).map(s => s.trim()).filter(Boolean) })
    keywords.value = await radarApi.keywords()
    message.value = '类目与种子词已保存；用于后续导入分类'
  })
}
function format(value: number | string | null | undefined, unit = '') { return value == null ? '待补充' : `${Number(value).toFixed(2)}${unit}` }
function date(value: string) { return new Date(value).toLocaleString('zh-CN') }
function focusDetails(event: Event) {
  event.preventDefault()
  const content = event.target as HTMLElement
  content?.focus({ preventScroll: true })
  if (content) content.scrollTop = 0
}
onMounted(async () => {
  await load()
  await act(async () => {
    categories.value = await radarApi.categories()
    keywords.value = await radarApi.keywords()
    const queue = await radarApi.queue(); queueSize.value = queue.jobs.length; breadth.value = queue.breadth_ratio * 100
  })
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="text-xs font-bold uppercase tracking-[.25em] text-teal-700">Xianyu Opportunity AI · P2</p>
        <h1 class="mt-2 flex items-center gap-2 text-3xl font-bold tracking-tight text-slate-900"><Radar class="h-7 w-7 text-teal-600" />选品雷达</h1>
        <p class="mt-2 text-sm text-slate-500">从商品观测发现方向，用证据决定下一步。</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <a href="/static/opportunity-guide.html" target="_blank" rel="noopener noreferrer" class="inline-flex items-center rounded-md border bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">使用指南</a>
        <Button variant="outline" :disabled="busy" @click="configOpen = true"><SlidersHorizontal class="mr-2 h-4 w-4" />类目与发现</Button>
        <Button variant="outline" :disabled="busy" @click="imported(radarApi.demo, 'demo')"><FlaskConical class="mr-2 h-4 w-4" />载入合成演示</Button>
        <Button :disabled="busy" @click="importOpen = true"><Upload class="mr-2 h-4 w-4" />导入 CSV / 下载模板</Button>
      </div>
    </div>

    <div class="rounded-xl border border-teal-200 bg-teal-50/80 px-5 py-4 text-sm leading-6 text-teal-900">
      <strong>本地证据工作台</strong> · 无需闲鱼 Cookie 或 AI Key。想要数、浏览量与报价均不代表真实销量或成交价；利润来自你填写的成本假设。演示数据明确标识为合成样例。
    </div>
    <OpportunityMonitorPanel @updated="() => { researchRevision++; load() }" @open-item="id => openItem({ id })" />
    <OpportunityResearchPanel :categories="categories" :revision="researchRevision" :preferred-scope="researchScope" @inspect="(category, keyword, scope) => { filters.category = category; filters.q = keyword; filters.source_scope = scope; load(true) }" />
    <p v-if="error" role="alert" class="rounded-lg bg-red-50 p-4 text-sm text-red-700">{{ error }}</p>
    <p v-if="message" role="status" class="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{{ message }}</p>
    <div v-if="report" role="status" class="rounded-lg border bg-white p-4 text-sm">
      已接受 {{ report.accepted }} 行 · 新商品 {{ report.inserted }} · 重复身份 {{ report.duplicates }} · 新快照 {{ report.new_snapshots }} · 拒绝 {{ report.rejected }} 行
      <details v-if="report.errors.length" class="mt-2 text-amber-800"><summary class="cursor-pointer">查看异常行（未入库）</summary><ul class="mt-2 space-y-1"><li v-for="r in report.errors" :key="r.line">第 {{ r.line }} 行：{{ r.reason }}</li></ul></details>
    </div>

    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4" role="tablist" aria-label="选品策略">
      <button v-for="mode in modes" :key="mode.key" role="tab" :aria-selected="filters.strategy === mode.key" class="rounded-xl border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:ring-teal-600" :class="filters.strategy === mode.key ? 'border-teal-600 bg-teal-700 text-white shadow-sm' : 'border-slate-200 bg-white/80 text-slate-600 hover:border-teal-300'" @click="filters.strategy = mode.key; load(true)">
        <span class="font-semibold">{{ mode.label }}</span><span class="mt-1 block text-xs leading-5" :class="filters.strategy === mode.key ? 'text-teal-100' : 'text-slate-500'">{{ mode.note }}</span>
      </button>
    </div>

    <Card><CardContent class="pt-5">
      <form class="grid items-end gap-4 sm:grid-cols-2 xl:grid-cols-4" @submit.prevent="load(true)">
        <label class="field">类目<select v-model="filters.category"><option value="">全部类目</option><option v-for="c in categories" :key="c.name" :value="c.name">{{ c.parent ? '　' : '' }}{{ c.name }}</option></select></label>
        <label class="field">关键词<input v-model="filters.q" type="search" placeholder="搜索商品标题" maxlength="200" /></label>
        <label class="field">最低预计净利率（%）<input v-model.number="filters.min_margin" type="number" min="-1000000" max="100" placeholder="不限，未知利润不参与筛选" @input="filters.min_margin = ($event.target as HTMLInputElement).value === '' ? undefined : Number(($event.target as HTMLInputElement).value)" /></label>
        <label class="field">最低可信度（0–100）<input v-model.number="filters.min_confidence" type="number" min="0" max="100" required /></label>
        <label class="field">数据来源<select v-model="filters.source_scope"><option value="all">全部（演示与导入分开分析）</option><option value="demo">仅合成演示</option><option value="imported">仅导入观测</option></select></label>
        <label class="field">排序<select v-model="filters.sort"><option value="score_total">选品评分</option><option value="confidence_score">数据可信度</option><option value="net_margin">预计净利率</option><option value="observed_at">最新观察时间</option></select></label>
        <label class="field">候选状态<select v-model="filters.pool"><option value="all">全部商品</option><option value="candidates">整个候选池</option><option value="candidate">候选待验证</option><option value="running">七天测试中</option><option value="completed">已完成测试</option><option value="stopped">已停止测试</option></select></label>
        <Button type="submit" :disabled="loading || busy">{{ loading ? '读取评分中…' : '应用筛选' }}</Button>
        <Button variant="outline" type="button" :disabled="busy" @click="imported(radarApi.importExisting, 'imported')">导入已有监控快照</Button>
      </form>
    </CardContent></Card>

    <div class="flex flex-wrap items-end justify-between gap-3">
      <div><h2 class="text-xl font-bold text-slate-900">{{ filters.pool === 'all' ? '商品机会排行榜' : '候选验证工作台' }} <span class="ml-2 text-sm font-normal text-slate-500">{{ total }} 个方向</span></h2><p class="mt-1 text-xs text-slate-500">本页 {{ items.length }} 件 · {{ knownMargin }} 件成本已补齐 · {{ demoCount }} 件为合成样例。候选仍需人工验证。</p></div>
      <a :href="radarApi.exportUrl(filters)" class="flex items-center text-sm font-semibold text-teal-700"><Download class="mr-1 h-4 w-4" />导出筛选结果 CSV</a>
    </div>
    <div class="overflow-x-auto rounded-xl border bg-white/90">
      <table class="w-full min-w-[760px] text-left text-sm">
        <thead class="border-b bg-slate-50 text-xs text-slate-500"><tr><th class="p-4">商品 / 观测来源</th><th class="p-4">报价</th><th class="p-4">评分 / 100</th><th class="p-4">可信度 / 100</th><th class="p-4">预计净利润</th><th class="p-4">验证状态</th></tr></thead>
        <tbody :aria-busy="loading">
          <tr v-for="item in items" :key="item.id" class="border-b last:border-0 hover:bg-teal-50/40">
            <td class="max-w-[340px] p-4"><button class="text-left font-semibold text-slate-900 hover:text-teal-700 hover:underline" :disabled="busy" @click="openItem(item)">{{ item.title }} <ArrowUpRight class="inline h-3 w-3" /></button><p class="mt-1 text-xs text-slate-500">{{ item.category }} · {{ item.source }} · {{ date(item.observed_at) }}</p><span v-if="item.score.is_demo" class="mt-2 inline-block rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-800">合成样例 · 非实时</span></td>
            <td class="p-4 tabular-nums">{{ item.currency }} {{ format(item.price) }}</td>
            <td class="p-4"><span class="text-lg font-bold text-teal-800">{{ item.score.score_total.toFixed(1) }}</span><div class="mt-1 h-1 w-16 rounded bg-slate-100"><div class="h-1 rounded bg-teal-500" :style="{ width: `${item.score.score_total}%` }" /></div></td>
            <td class="p-4 tabular-nums">{{ item.score.confidence_score.toFixed(1) }}<p class="mt-1 text-xs text-slate-400">独立证据评价</p></td>
            <td class="p-4 tabular-nums">{{ format(item.score.profit.net_profit) }}<p class="mt-1 text-xs text-slate-500">净利率 {{ format(item.score.profit.net_margin, '%') }}</p></td>
            <td class="p-4"><span class="rounded-full px-2 py-1 text-xs" :class="item.score.blockers.length ? 'bg-amber-50 text-amber-900' : 'bg-teal-50 text-teal-800'">{{ item.score.blockers.length ? `${item.score.blockers.length} 项需核验` : '可进入人工验证' }}</span><p v-if="item.experiment_status" class="mt-2 text-xs text-teal-700">{{ poolLabels[item.experiment_status] || item.experiment_status }}</p></td>
          </tr>
          <tr v-if="!items.length"><td colspan="6" class="px-6 py-16 text-center text-slate-500">{{ loading ? '正在读取 SQLite…' : filters.pool === 'all' ? '暂无符合条件的商品。导入 CSV 或载入合成演示，开始选品。' : '暂无符合条件的候选。可先将商品纳入候选池，或调整验证状态及来源筛选。' }}</td></tr>
        </tbody>
      </table>
    </div>
    <div class="flex items-center justify-end gap-3 text-sm text-slate-500"><Button variant="outline" :disabled="page <= 1 || loading" @click="page--; load()">上一页</Button><span>第 {{ page }} / {{ pageCount }} 页</span><Button variant="outline" :disabled="page >= pageCount || loading" @click="page++; load()">下一页</Button></div>

    <Dialog v-model:open="detailOpen"><DialogContent class="z-[120] max-h-[90vh] overflow-y-auto sm:max-w-3xl" @open-auto-focus="focusDetails">
      <DialogHeader><DialogTitle>{{ selected?.title }}</DialogTitle><DialogDescription>评分依据、未知项与成本假设；全部可追溯到本地观测。</DialogDescription></DialogHeader>
      <div v-if="selected" class="min-w-0 space-y-5 text-sm">
        <OpportunityHistoryPanel :item-id="selected.id" />
        <div class="grid gap-2 rounded-lg bg-slate-50 p-4 sm:grid-cols-2"><p>来源：{{ selected.source }} / {{ selected.source_item_id }}</p><p>最新观察：{{ date(selected.observed_at) }}</p><p>首次观察：{{ date(selected.first_observed_at) }}</p><p>真实发布时间：{{ selected.listing_created_at ? date(selected.listing_created_at) : '未知' }}</p><p>有效快照 {{ selected.observation_count }} 个；{{ selected.baseline_only ? '仅观察基线' : '多次记录，未推断成交' }}</p><a v-if="selected.url" :href="selected.url" target="_blank" rel="noopener noreferrer" class="text-teal-700 underline">{{ selected.score.is_demo ? '合成占位链接（不可访问）' : '打开来源链接' }}</a><p>想要 {{ selected.want_count ?? '未知' }} / 浏览 {{ selected.view_count ?? '未知' }}</p><p>本地报价区间 {{ format(selected.score.market.price_low) }}–{{ format(selected.score.market.price_high) }} {{ selected.currency }}（{{ selected.score.market.sample_count }} 条）</p></div>
        <div><h3 class="mb-3 font-bold">评分 {{ selected.score.score_total }} · 可信度 {{ selected.score.confidence_score }}</h3><div class="grid gap-3 sm:grid-cols-2"><div v-for="(d, key) in selected.score.dimensions" :key="key" class="rounded-lg border p-3"><div class="flex justify-between font-semibold"><span>{{ dimensionLabels[key] }}</span><span>{{ d.score }} × {{ d.weight }}%</span></div><p class="mt-2 text-xs leading-5 text-slate-500">{{ d.evidence }}</p></div></div><p class="mt-3 text-xs text-slate-500">可信度依据：来源系数 {{ selected.score.confidence_basis.source_confidence }} × 覆盖率 {{ selected.score.confidence_basis.coverage }} × 时效 {{ selected.score.confidence_basis.freshness_factor }}；合成样例最高 20 分。</p></div>
        <div class="rounded-lg bg-amber-50 p-4 text-amber-900"><h3 class="font-bold">风险与待补充</h3><ul class="mt-2 list-inside list-disc space-y-1"><li v-for="b in selected.score.blockers" :key="b">{{ b }}</li></ul><p class="mt-2 break-words text-xs">缺失字段：{{ selected.score.missing.join('、') || '当前规则字段已填写，仍需人工验证' }}</p></div>
        <ul class="list-inside list-disc space-y-1 text-xs leading-5 text-slate-500"><li v-for="warning in selected.score.warnings" :key="warning">{{ warning }}</li></ul>
        <div v-if="selected.suspected_duplicates?.length"><h3 class="font-bold">疑似重复（未合并）</h3><p v-for="d in selected.suspected_duplicates" :key="d.id" class="mt-1 text-xs text-slate-500">#{{ d.id }} {{ d.title }} · 相似度 {{ d.similarity }} · {{ d.basis }}</p></div>
        <form class="space-y-4 border-t pt-4" @submit.prevent="saveCosts"><h3 class="font-bold">计算假设（{{ selected.currency }}）</h3><p class="text-xs text-slate-500">预计净利润 = 预计成交价 − 采购 − 运费 − 平台费用 − 履约 − 损耗。明确为零才填写 0；未知请留空。保存将替换当前假设。</p><div class="grid grid-cols-2 gap-3 sm:grid-cols-3"><label v-for="(label, key) in costLabels" :key="key" class="field">{{ label }}<input v-model="costDraft[key]" type="number" min="0" max="1000000000" step="0.01" placeholder="待补充" /></label></div><div class="grid gap-3 sm:grid-cols-2"><label v-for="(label, key) in evidenceLabels" :key="key" class="field">{{ label }}<textarea v-model="costDraft[key]" rows="2" :maxlength="key === 'evidence_note' ? 2000 : 1000" placeholder="来源、日期、凭据说明（请勿填写账号密钥）" /></label></div><div class="flex flex-wrap gap-3"><Button type="submit" :disabled="busy">保存假设并重新评分</Button><Button variant="outline" type="button" :disabled="busy" @click="addCandidate">{{ selected.experiment_status ? '已在候选池' : '纳入候选池' }}</Button></div><p v-if="error" role="alert" class="text-red-700">{{ error }}</p><p v-if="message" role="status" class="text-teal-700">{{ message }}</p></form>
        <OpportunityBusinessPanel :item-id="selected.id" :strategy="filters.strategy" :revision="businessRevision" @updated="refreshSelected" />
      </div>
    </DialogContent></Dialog>

    <OpportunityImportDialog v-model:open="importOpen" @imported="importedFile" />
    <Dialog v-model:open="configOpen"><DialogContent class="z-[120] max-h-[90vh] overflow-y-auto sm:max-w-2xl"><DialogHeader><DialogTitle>类目与关键词发现</DialogTitle><DialogDescription>离线规则可用；候选词及队列均有上限，保存后用于后续导入。</DialogDescription></DialogHeader>
      <form class="space-y-3" @submit.prevent="saveCategory"><label class="field">编辑已有类目或新增<select @change="editCategory"><option value="">新增类目</option><option v-for="c in categories" :key="c.name" :value="c.name">{{ c.name }}</option></select></label><div class="grid gap-3 sm:grid-cols-2"><label class="field">类目名称<input v-model="config.name" required maxlength="100" placeholder="例如：户外照明" /></label><label class="field">一级类目<select v-model="config.parent"><option :value="null">设为一级类目</option><option v-for="c in categories.filter(c => !c.parent && c.name !== config.name)" :key="c.name" :value="c.name">{{ c.name }}</option></select></label></div><label class="field">种子词（逗号或换行分隔，最多 30 个）<textarea v-model="seedText" rows="2" /></label><Button :disabled="busy" type="submit">保存类目与种子词</Button></form>
      <div class="space-y-3 border-t pt-4"><div class="grid grid-cols-2 gap-3"><label class="field">广度探索占比（%）<input v-model.number="breadth" type="number" min="0" max="100" /></label><label class="field">本次队列预算（1–50）<input v-model.number="budget" type="number" min="1" max="50" /></label></div><p class="text-xs text-slate-500">默认 40% 广度 / 60% 深挖是启发式配置；队列最多 200 条，仅人工待办，不执行外部采集。</p><div class="flex flex-wrap gap-2"><Button variant="outline" :disabled="busy" @click="act(async () => { const r = await radarApi.expand(); keywords = await radarApi.keywords(); message = `新增 ${r.added} 个候选词，未验证搜索量` })">离线扩展关键词</Button><Button variant="outline" :disabled="busy" @click="act(async () => { const r = await radarApi.plan(budget, breadth / 100); queueSize = r.jobs.length; message = r.note })">生成发现待办</Button></div><p class="text-sm">待办 {{ queueSize }} 条 · 最近 {{ keywords.length }} 个候选词</p><div class="max-h-48 space-y-2 overflow-y-auto"><div v-for="k in keywords.slice(0, 40)" :key="k.id" class="rounded border p-2"><p class="text-sm font-semibold">{{ k.keyword }} <span class="font-normal text-slate-500">· {{ k.category }}</span></p><p class="text-xs text-slate-500">来源 {{ k.origin }} · {{ date(k.discovered_at) }}</p></div></div></div><p v-if="message" role="status" class="text-sm text-teal-700">{{ message }}</p><p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
    </DialogContent></Dialog>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: .4rem; font-size: .75rem; font-weight: 600; color: #475569; }
.field input, .field select, .field textarea { width: 100%; border: 1px solid #cbd5e1; border-radius: .5rem; padding: .6rem .7rem; background: white; font-size: .875rem; font-weight: 400; color: #0f172a; }
.field input:focus, .field select:focus, .field textarea:focus { outline: 2px solid #0d9488; outline-offset: 2px; }
</style>
