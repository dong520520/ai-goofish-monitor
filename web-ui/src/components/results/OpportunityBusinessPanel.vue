<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { radarApi, type BusinessDossier, type SupplierQuote, type Strategy } from '@/api/opportunities'
import { Button } from '@/components/ui/button'

const props = defineProps<{ itemId: number; strategy: Strategy; revision: number }>()
const emit = defineEmits<{ updated: [] }>()
const dossier = ref<BusinessDossier | null>(null), quotes = ref<SupplierQuote[]>([])
const busy = ref(false), error = ref(''), message = ref(''), quoteId = ref<number | null>(null), confirmed = ref(false), identityNote = ref('')
const quotePage = ref(1), quoteTotal = ref(0)
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const config = reactive({ start_date: today(), status: 'running', stop_reason: '' })
const draft = ref<Record<string, string | number | null>>({ day: today(), evidence_note: '' })
const financial: Record<string, string> = { revenue: '销售收入（退款前）', refund_amount: '实际退款金额', purchase_cost: '实际采购合计', shipping_cost: '实际运费', platform_fee: '实际平台费用', fulfillment_cost: '实际履约费用', actual_loss: '其他实际损耗（不重复记退款）' }
const metrics: Record<string, string> = { exposure: '曝光（可未知）', inquiries: '咨询', orders: '订单', refunds: '退款单' }
const decisions: Record<string, string> = { continue: '继续验证', test: '继续记录测试', fill_evidence: '补充证据', stop: '停止并复核' }
async function loadQuotes() {
  const result = await radarApi.quotes(dossier.value?.is_demo ? 'demo' : 'imported', quotePage.value)
  quotes.value = result.items; quoteTotal.value = result.total
}
async function load() {
  dossier.value = await radarApi.business(props.itemId)
  if (dossier.value.config) Object.assign(config, dossier.value.config)
  await loadQuotes()
}
async function act(action: () => Promise<unknown>) {
  busy.value = true; error.value = ''; message.value = ''
  try { await action() } catch (e) { error.value = (e as Error).message } finally { busy.value = false }
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  if (!file) return
  if (file.size > 2_000_000) { error.value = '报价 CSV 最大2MB'; input.value = ''; return }
  await act(async () => {
    const result = await radarApi.importQuotes(await file.text())
    message.value = `接受 ${result.accepted} 行，新增版本 ${result.inserted}，拒绝 ${result.rejected}。${result.errors.map(e => `第${e.line}行：${e.reason}`).join('；')}`
    await loadQuotes()
  })
  input.value = ''
}
async function link() {
  if (!quoteId.value || !confirmed.value) return
  await act(async () => {
    await radarApi.confirmQuote(props.itemId, quoteId.value!, identityNote.value)
    await load(); emit('updated'); message.value = '已人工关联到原成本假设，请补齐其余费用并核对预计净利润。'
  })
}
async function saveConfig() {
  await act(async () => {
    await radarApi.candidate(props.itemId, props.strategy)
    await radarApi.experiment(props.itemId, { start_date: config.start_date, status: config.status, stop_reason: config.stop_reason })
    await load(); emit('updated'); message.value = '七天人工实验已保存。'
  })
}
async function saveEntry() {
  await act(async () => {
    const payload: Record<string, unknown> = { day: draft.value.day, evidence_note: draft.value.evidence_note }
    for (const key of Object.keys(financial)) payload[key] = draft.value[key] === '' ? null : draft.value[key] ?? null
    for (const key of Object.keys(metrics)) payload[key] = draft.value[key] === '' || draft.value[key] == null ? null : Number(draft.value[key])
    await radarApi.recordEntry(props.itemId, payload)
    await load(); message.value = '当日记录已保存；同一天重复保存为修订。'
  })
}
function editEntry(data: Record<string, string | number | null>) { draft.value = { ...data } }
watch(() => props.itemId, () => { quotePage.value = 1; draft.value = { day: today(), evidence_note: '' }; confirmed.value = false; identityNote.value = ''; quoteId.value = null; Object.assign(config, { start_date: today(), status: 'running', stop_reason: '' }); act(load) })
watch(() => props.revision, () => act(load))
onMounted(() => act(load))
</script>

<template>
  <section class="space-y-4 border-t pt-5">
    <h3 class="font-bold">货源报价与七天经营验证</h3>
    <p class="text-xs leading-5 text-slate-500">报价由你提供并核对身份，系统没有独立核实。采购单价和运费均按每次销售口径填写；MOQ另行展示。经营账本仅记录自己的实际结果，未知留空，明确为零才填0。</p>
    <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p><p v-if="message" role="status" class="text-sm text-teal-800">{{ message }}</p>
    <details class="rounded-lg border p-4" open>
      <summary class="cursor-pointer font-semibold">人工报价与成本来源</summary>
      <div class="mt-3 flex flex-wrap items-center gap-3"><label class="cursor-pointer rounded border px-3 py-2 text-xs">导入货源 CSV<input aria-label="导入货源 CSV" type="file" accept=".csv,text/csv" class="sr-only" :disabled="busy" @change="upload" /></label><a :href="radarApi.supplierInquiryUrl(itemId)" class="text-xs text-teal-700 underline">下载该商品询价模板</a><a :href="radarApi.supplierInquiryUrl()" class="text-xs text-teal-700 underline">下载空白报价模板</a><a :href="radarApi.supplierTemplateUrl" class="text-xs text-slate-500 underline">查看合成格式样例</a></div>
      <p class="mt-2 text-xs leading-5 text-amber-800">询价模板仅预填已有商品描述、币种及明确记录的身份字段。观测报价不会填作采购价；供应商、真实 SKU / 规格 / 成色、报价时间和费用须据实补齐后再导入。填写模板不会自动核验或关联货源。</p>
      <div v-if="dossier?.linked_quote" class="mt-3 rounded bg-teal-50 p-3 text-xs leading-6"><strong>当前报价 #{{ dossier.linked_quote.quote_id }}</strong> · {{ dossier.linked_quote.quote.supplier }} / {{ dossier.linked_quote.quote.sku }} / {{ dossier.linked_quote.quote.specification }}<br />{{ dossier.linked_quote.confirmation_note }}<br />最低起订采购支出：{{ dossier.linked_quote.minimum_purchase_outlay ?? '未知' }} {{ dossier.currency }}（采购单价 × MOQ，不含其他费用）<p v-if="!dossier.linked_quote.current_costs_match_quote" class="text-amber-800">当前采购/运费或货源说明已被修改，请重新核对报价关联。</p></div>
      <form class="mt-4 space-y-3" @submit.prevent="link">
        <label class="business-field">选择报价版本<select v-model.number="quoteId" required><option :value="null">请选择，逐项核实身份</option><option v-for="q in quotes" :key="q.id" :value="q.id">#{{ q.id }} {{ q.supplier }} · {{ q.sku }} / {{ q.specification }} / {{ q.condition }} · {{ q.currency }} {{ q.purchase_cost ?? '未知' }}</option></select></label>
        <div class="flex items-center justify-between text-xs"><Button type="button" size="sm" variant="outline" :disabled="busy || quotePage <= 1" @click="act(async () => { quotePage--; await loadQuotes() })">上一页报价</Button><span>{{ quotePage }} / {{ Math.max(1, Math.ceil(quoteTotal / 50)) }} 页</span><Button type="button" size="sm" variant="outline" :disabled="busy || quotePage * 50 >= quoteTotal" @click="act(async () => { quotePage++; await loadQuotes() })">下一页报价</Button></div>
        <div v-if="quotes.find(q => q.id === quoteId)" class="rounded bg-slate-50 p-3 text-xs leading-6"><template v-for="q in quotes.filter(q => q.id === quoteId)" :key="q.id">{{ q.source }}/{{ q.quote_id }} · {{ q.quoted_at }}<br />单价 {{ q.purchase_cost ?? '未知' }} / 运费 {{ q.shipping_cost ?? '未知' }} {{ q.currency }} · MOQ {{ q.moq ?? '未知' }} · 交期 {{ q.lead_days ?? '未知' }} 天 · 来源自评 {{ q.source_confidence }}<p>{{ q.evidence_note }}</p><p>{{ q.verification_note || '无核验备注，待人工验证' }}</p></template></div>
        <label class="business-field">身份核对说明<textarea v-model="identityNote" minlength="5" maxlength="1000" required rows="2" placeholder="核对型号、SKU、规格、成色、币种及交付口径" /></label>
        <label class="flex items-center gap-2 text-xs"><input v-model="confirmed" type="checkbox" required />我已逐项核对以上报价与该候选商品身份</label>
        <Button type="submit" :disabled="busy || !confirmed || !quoteId">确认关联并更新原成本</Button>
      </form>
    </details>
    <details class="rounded-lg border p-4">
      <summary class="cursor-pointer font-semibold">七天自营测试与复盘</summary>
      <form class="mt-4 space-y-3" @submit.prevent="saveConfig"><div class="grid gap-3 sm:grid-cols-2"><label class="business-field">开始日期（中国时区）<input v-model="config.start_date" type="date" :max="today()" required /></label><label class="business-field">状态<select v-model="config.status"><option value="running">进行中</option><option value="completed">七天已完成</option><option value="stopped">已停止</option></select></label></div><label class="business-field">停止原因<textarea v-model="config.stop_reason" :required="config.status === 'stopped'" maxlength="1000" /></label><Button type="submit" :disabled="busy">纳入候选并保存实验</Button></form>
      <template v-if="dossier?.config">
        <div v-if="dossier.review" class="my-4 rounded bg-slate-50 p-3 text-xs leading-6"><strong>{{ decisions[dossier.review.decision] }}</strong> · 已记录 {{ dossier.review.recorded_days }}/7 天<p v-for="r in dossier.review.reasons" :key="r">{{ r }}</p><p>已记录期间净收益 {{ dossier.review.recorded_net ?? '未知' }}；完整七天净收益 {{ dossier.review.seven_day_net ?? '未知' }} {{ dossier.currency }}</p><p>未记录日期：{{ dossier.review.missing_days.join('、') || '无' }}</p><p v-for="m in dossier.review.missing_finances" :key="m" class="text-amber-800">{{ m }}</p><p>{{ dossier.review.note }}</p></div>
        <div class="space-y-2 text-xs"><button v-for="e in dossier.entries" :key="String(e.data.day)" class="mr-2 rounded border px-2 py-1 text-teal-700" @click="editEntry(e.data)">{{ e.data.day }} · 净收益 {{ e.profit.net_profit ?? '未知' }} · 编辑</button><a :href="radarApi.ledgerExportUrl(itemId)" class="text-teal-700 underline">导出账本 CSV</a></div>
        <form class="mt-4 space-y-3" @submit.prevent="saveEntry"><label class="business-field">经营日期<input v-model="draft.day" type="date" :min="dossier.config.start_date" :max="today()" required /></label><div class="grid grid-cols-2 gap-3"><label v-for="(label, key) in metrics" :key="key" class="business-field">{{ label }}<input v-model="draft[key]" type="number" min="0" max="1000000000" step="1" placeholder="未知" /></label><label v-for="(label, key) in financial" :key="key" class="business-field">{{ label }}（{{ dossier.currency }}）<input v-model="draft[key]" type="number" min="0" max="1000000000" step="0.01" placeholder="未知" /></label></div><label class="business-field">记录依据<textarea v-model="draft.evidence_note" maxlength="2000" required placeholder="自营订单、退款和费用记录出处，不填客户隐私或密钥" /></label><Button type="submit" :disabled="busy">保存当日实际记录</Button></form>
      </template>
    </details>
  </section>
</template>

<style scoped>
.business-field { display: flex; flex-direction: column; gap: .35rem; font-size: .75rem; color: #475569; }
.business-field input, .business-field select, .business-field textarea { min-width: 0; width: 100%; border: 1px solid #cbd5e1; border-radius: .5rem; padding: .5rem; color: #0f172a; background: white; }
</style>
