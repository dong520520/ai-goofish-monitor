<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { radarApi, type ObservedSeller, type SellerItem, type SyncStatus } from '@/api/opportunities'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
const emit = defineEmits<{ updated: []; openItem: [id: number] }>()
const status = ref<SyncStatus | null>(null), busy = ref(false), error = ref(''), message = ref('')
const sellersOpen = ref(false), sellers = ref<ObservedSeller[]>([]), sellerTotal = ref(0), sellerPage = ref(1)
const sellerScope = ref('all'), watchedOnly = ref(false), chosenSeller = ref<ObservedSeller | null>(null), sellerItems = ref<SellerItem[]>([]), sellerItemTotal = ref(0)
async function action(callback: () => Promise<void>) {
  busy.value = true; error.value = ''; message.value = ''
  try { await callback() } catch (e) { error.value = (e as Error).message } finally { busy.value = false }
}
async function refresh() {
  const previous = status.value
  status.value = await radarApi.syncStatus()
  if (previous && previous.last_run_at !== status.value.last_run_at) emit('updated')
}
async function sync() {
  await action(async () => {
    const result = await radarApi.sync(); await refresh()
    message.value = result.paused ? '同步已暂停，请处理状态提示后恢复' : `本批处理 ${result.processed} 条 · 新快照 ${result.new_snapshots} · 异常 ${result.rejected}`
  })
}
async function loadSellers(reset = false) {
  if (reset) sellerPage.value = 1
  chosenSeller.value = null
  const result = await radarApi.sellers(sellerPage.value, sellerScope.value, watchedOnly.value)
  sellers.value = result.items; sellerTotal.value = result.total
}
async function openSellers() { await action(async () => { await loadSellers(true); sellersOpen.value = true }) }
async function selectSeller(seller: ObservedSeller) {
  await action(async () => { const result = await radarApi.sellerItems(seller); chosenSeller.value = seller; sellerItems.value = result.items; sellerItemTotal.value = result.total })
}
function openItem(id: number) { sellersOpen.value = false; emit('openItem', id) }
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  void action(refresh)
  timer = setInterval(() => {
    if (!document.hidden && !busy.value) void refresh().catch(e => { error.value = (e as Error).message })
  }, 60000)
})
onUnmounted(() => clearInterval(timer))
</script>
<template>
  <section class="space-y-3 rounded-xl border border-slate-200 bg-white/80 p-5" aria-label="持续观测控制">
    <div class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="font-bold text-slate-900">持续观测 <span class="ml-2 text-xs font-normal" :class="status?.enabled ? 'text-teal-700' : 'text-amber-800'">{{ status?.enabled ? '本地同步已启用' : status ? '本地同步已暂停' : '读取状态中' }}</span></h2><p class="mt-1 text-xs text-slate-500">每60秒同步已有监控结果及价格快照，每表最多100条；不会发起平台请求。</p></div><div class="flex flex-wrap gap-2"><Button variant="outline" size="sm" :disabled="busy || !status?.enabled" @click="sync">同步一批</Button><Button variant="outline" size="sm" :disabled="busy || !status" @click="action(async () => { status = await radarApi.configureSync(!status!.enabled) })">{{ status?.enabled ? '暂停同步' : '恢复同步' }}</Button><Button variant="outline" size="sm" :disabled="busy" @click="action(async () => { const r = await radarApi.historyDemo(); message = `合成变化演示：新增 ${r.new_snapshots} 条快照；异常 ${r.rejected} 行`; emit('updated') })">载入变化演示</Button><Button variant="outline" size="sm" :disabled="busy" @click="openSellers">卖家记录</Button></div></div>
    <p v-if="status" class="text-xs text-slate-500">待同步 {{ Object.values(status.pending).reduce((a,b) => a+b,0) }} 条 · 历史异常 {{ status.rejected_count }} 条 · 上次处理 {{ status.last_run_at ? new Date(status.last_run_at).toLocaleString('zh-CN') : '尚未处理' }} <button class="ml-2 text-teal-700 underline" :disabled="busy" @click="action(refresh)">刷新状态</button></p>
    <p v-if="status?.last_error" role="alert" class="text-sm text-amber-800">{{ status.last_error }}</p><p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p><p v-if="message" role="status" class="text-sm text-teal-700">{{ message }}</p>
    <details v-if="status?.rejections.length" class="text-xs text-slate-500"><summary class="cursor-pointer">最近异常（保留原数据，未补造指标）</summary><p v-for="r in status.rejections" :key="`${r.origin}:${r.row_id}`" class="mt-2">{{ r.origin }} #{{ r.row_id }}：{{ r.reason }}</p></details>
    <Dialog v-model:open="sellersOpen"><DialogContent class="z-[120] max-h-[90vh] overflow-y-auto sm:max-w-3xl"><DialogHeader><DialogTitle>已观察卖家记录</DialogTitle><DialogDescription>仅展示稳定ID与已观察商品的历史关联。关注只保存在本地，不扫描店铺；数量不是当前在售数。</DialogDescription></DialogHeader>
      <div class="flex flex-wrap gap-3 text-sm"><label>来源 <select v-model="sellerScope" class="rounded border p-2" @change="action(() => loadSellers(true))"><option value="all">全部</option><option value="demo">合成演示</option><option value="imported">导入观测</option></select></label><label class="flex items-center gap-2"><input v-model="watchedOnly" type="checkbox" @change="action(() => loadSellers(true))" />仅已关注</label></div>
      <p class="text-xs text-slate-500">{{ sellerTotal }} 个已观察卖家 · 第 {{ sellerPage }} 页</p>
      <div class="space-y-2"><div v-for="seller in sellers" :key="`${seller.source}:${seller.seller_id}`" class="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3"><button class="text-left text-sm font-semibold text-teal-800 hover:underline" :disabled="busy" @click="selectSeller(seller)">{{ seller.seller_id }}<span class="mt-1 block text-xs font-normal text-slate-500">{{ seller.source }} · 关联 {{ seller.observed_items }} 件 · 最后观察 {{ new Date(seller.last_observed_at).toLocaleString('zh-CN') }}</span></button><Button variant="outline" size="sm" :disabled="busy" @click="action(async () => { await radarApi.watchSeller(seller); await loadSellers() })">{{ seller.watching ? '取消本地关注' : '本地关注' }}</Button></div></div>
      <div class="flex justify-end gap-2"><Button variant="outline" size="sm" :disabled="busy || sellerPage <= 1" @click="action(async () => { sellerPage--; await loadSellers() })">上一页</Button><Button variant="outline" size="sm" :disabled="busy || sellerPage * 20 >= sellerTotal" @click="action(async () => { sellerPage++; await loadSellers() })">下一页</Button></div>
      <div v-if="chosenSeller" class="space-y-2 border-t pt-4"><h3 class="font-semibold">{{ chosenSeller.seller_id }} 的已观察商品</h3><p class="text-xs text-slate-500">共 {{ sellerItemTotal }} 件，显示最近20件。关联可来自历史快照，不代表当前归属。</p><button v-for="item in sellerItems" :key="item.id" class="block text-left text-sm text-teal-800 hover:underline" :disabled="busy" @click="openItem(item.id)">{{ item.title }} · {{ new Date(item.last_associated_at).toLocaleString('zh-CN') }}</button></div>
      <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
    </DialogContent></Dialog>
  </section>
</template>
