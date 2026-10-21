<script setup lang="ts">
import { ref, watch } from 'vue'
import { radarApi, type ImportPreview, type ImportReport } from '@/api/opportunities'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean]; imported: [report: ImportReport, scope: string] }>()
const preview = ref<ImportPreview | null>(null), content = ref(''), fileName = ref(''), error = ref('')
const checking = ref(false), importing = ref(false)
const actionLabels: Record<string, string> = { new_item: '新商品', new_snapshot: '新增观测', duplicate: '重复快照' }
const fieldLabels: Record<string, string> = { price: '报价', seller_id: '稳定卖家ID', condition: '成色', listing_created_at: '真实发布时间', want_count: '想要数', view_count: '浏览量' }
let generation = 0
function close(value: boolean) { if (!importing.value) emit('update:open', value) }
watch(() => props.open, value => {
  if (!value) { generation++; content.value = ''; fileName.value = ''; preview.value = null; error.value = ''; checking.value = false }
})
async function upload(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  if (!file) return
  const request = ++generation
  preview.value = null; content.value = ''; fileName.value = file.name; error.value = ''
  if (file.size > 2_000_000) { error.value = 'CSV 最大2MB，请分批上传'; input.value = ''; return }
  checking.value = true
  try {
    const text = await file.text()
    const result = await radarApi.previewCSV(text)
    if (request === generation) { content.value = text; preview.value = result }
  } catch (e) { if (request === generation) error.value = (e as Error).message }
  finally { if (request === generation) checking.value = false; input.value = '' }
}
async function confirm() {
  if (!preview.value?.accepted || importing.value) return
  importing.value = true; error.value = ''
  try {
    const sources = Object.keys(preview.value.source_counts)
    const scope = sources.every(s => s === 'synthetic_demo') ? 'demo' : sources.every(s => s !== 'synthetic_demo') ? 'imported' : 'all'
    const result = await radarApi.importCSV(content.value)
    emit('imported', result, scope)
    emit('update:open', false)
  } catch (e) { error.value = (e as Error).message }
  finally { importing.value = false }
}
</script>

<template>
  <Dialog :open="open" @update:open="close"><DialogContent class="z-[120] max-h-[90vh] w-[calc(100%_-_2rem)] min-w-0 overflow-y-auto sm:max-w-3xl">
    <DialogHeader><DialogTitle>导入商品观测 · 先预检再保存</DialogTitle><DialogDescription>使用你有权使用的UTF-8商品CSV。预检不保存商品、快照、成本或导入记录。</DialogDescription></DialogHeader>
    <div class="min-w-0 space-y-4 text-sm [overflow-wrap:anywhere]">
      <div class="rounded-lg bg-teal-50 p-4 text-xs leading-6 text-teal-900"><strong>准备真实选品数据</strong><p>必填来源 source、稳定商品ID source_item_id、标题 title、带时区的观察时间 observed_at。报价、成色及已知证据尽量补齐；未知留空，明确为零才填0。</p><div class="mt-2 flex flex-wrap gap-4"><a :href="radarApi.importTemplateUrl()" class="font-semibold underline">下载基础空白模板</a><a :href="radarApi.importTemplateUrl('costs')" class="font-semibold underline">下载含成本空白模板</a><a href="/static/opportunity-guide.html#real" target="_blank" rel="noopener noreferrer" class="underline">字段填写说明</a></div><p>模板只有表头，没有编造的商品。先填少量同类目观测，再分批扩大；每批最多2MB、1000行。</p></div>
      <label class="flex cursor-pointer flex-wrap items-center gap-3 rounded-lg border border-dashed p-4"><span class="rounded bg-slate-900 px-3 py-2 text-xs text-white">选择CSV并预检</span><span class="break-all text-xs text-slate-500">{{ fileName || '尚未选择文件' }}</span><input aria-label="选择商品 CSV 进行预检" class="sr-only" type="file" accept=".csv,text/csv" :disabled="checking || importing" @change="upload" /></label>
      <p v-if="checking" role="status" class="text-teal-700">正在校验字段、去重和检查已有记录…</p><p v-if="error" role="alert" class="break-words text-red-700">{{ error }}</p>
      <template v-if="preview">
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4"><div class="rounded-lg border p-3"><strong class="text-xl">{{ preview.accepted }}</strong><p class="text-xs text-slate-500">有效行 / 共{{ preview.total_rows }}行</p></div><div class="rounded-lg border p-3"><strong class="text-xl">{{ preview.inserted }}</strong><p class="text-xs text-slate-500">预计新商品</p></div><div class="rounded-lg border p-3"><strong class="text-xl">{{ preview.new_snapshots }}</strong><p class="text-xs text-slate-500">预计新快照</p></div><div class="rounded-lg border p-3"><strong class="text-xl text-amber-800">{{ preview.rejected }}</strong><p class="text-xs text-slate-500">错误行，将跳过</p></div></div>
        <div class="space-y-1 rounded-lg bg-slate-50 p-3 text-xs leading-6"><p>来源：<span v-for="(count, source) in preview.source_counts" :key="source" class="mr-3">{{ source }} {{ count }}行</span></p><p>类目：<span v-for="(count, name) in preview.category_counts" :key="name" class="mr-3">{{ name }} {{ count }}行</span></p><p>币种：<span v-for="(count, currency) in preview.currency_counts" :key="currency" class="mr-3">{{ currency }} {{ count }}行</span></p><p>按来源与ID识别的已有商品行 {{ preview.duplicates }}；成本仍不足以计算净收益 {{ preview.unknown_profit_rows }}行。</p><p v-if="preview.source_counts.synthetic_demo" class="text-amber-800">包含{{ preview.source_counts.synthetic_demo }}行合成样例，将继续隔离于真实观测。</p><p v-if="preview.older_observations" class="text-amber-800">{{ preview.older_observations }}行较早观测仅补历史，不覆盖最新报价与成本。</p><p v-for="(count, field) in preview.missing_counts" :key="field" class="text-amber-800">{{ fieldLabels[field] || field }}未知：{{ count }}行</p></div>
        <details v-if="preview.errors.length" class="rounded-lg border border-amber-200 p-3 text-xs text-amber-900" open><summary class="cursor-pointer font-semibold">错误行原因</summary><p v-for="e in preview.errors" :key="e.line" class="mt-2 break-words">第{{ e.line }}行：{{ e.reason }}</p></details>
        <div class="overflow-x-auto"><table class="w-full min-w-[560px] text-left text-xs"><thead class="border-b text-slate-500"><tr><th class="p-2">行号</th><th class="p-2">商品</th><th class="p-2">类目 / 来源</th><th class="p-2">报价</th><th class="p-2">预计处理</th></tr></thead><tbody><tr v-for="s in preview.sample" :key="s.line" class="border-b"><td class="p-2">{{ s.line }}</td><td class="max-w-60 break-words p-2">{{ s.title }}</td><td class="p-2">{{ s.category }}<br />{{ s.source }}</td><td class="p-2">{{ s.currency }} {{ s.price ?? '未知' }}</td><td class="p-2">{{ actionLabels[s.action] }}</td></tr></tbody></table></div>
        <p class="text-xs leading-6 text-slate-500">{{ preview.note }} <span v-if="preview.sample_truncated">上方仅展示前20条有效样本。</span>分类、来源及缺失统计按有效行计，包含重复行，不代表独立商品数或市场规模。</p>
        <div class="flex flex-wrap gap-3"><Button :disabled="importing || !preview.accepted" @click="confirm">{{ importing ? '正在保存…' : `确认导入${preview.accepted}条有效行` }}</Button><Button variant="outline" :disabled="importing" @click="close(false)">取消，不导入</Button></div>
      </template>
    </div>
  </DialogContent></Dialog>
</template>
