import { http } from '@/lib/http'

export type Strategy = 'physical' | 'virtual' | 'resale' | 'blue_ocean'
export interface Category { name: string; parent: string | null; keywords: string[] }
export interface MarketCohort {
  source: string; category: string; currency: string; condition: string | null; model: string | null; sku: string | null; specification: string | null
  sample_count: number; priced_count: number; distinct_sellers: number | null; p25: string | null; p50: string | null; p75: string | null
  want_coverage: number; view_coverage: number; confidence_score: number; missing: string[]; item_ids: number[]; is_demo: boolean
}
export interface MarketEvidence {
  cohorts: MarketCohort[]; total_cohorts: number; truncated: boolean; note: string
  category_coverage: { category: string; sample_count: number }[]
  lineage: { id: number; keyword: string; origin: string; category: string; matched_count: number; item_ids: number[] }[]
}
export interface SupplierQuote {
  id: number; source: string; quote_id: string; supplier: string; product: string; sku: string; specification: string
  condition: string; currency: string; quoted_at: string; purchase_cost: string | null; shipping_cost: string | null
  lead_days: number | null; moq: number | null; source_confidence: number; evidence_note: string; verification_note: string
}
export interface BusinessDossier {
  currency: string; is_demo: boolean
  linked_quote: { quote_id: number; quote: SupplierQuote; confirmation_note: string; linked_at: string; current_costs_match_quote: boolean; minimum_purchase_outlay: string | null } | null
  config: { start_date: string; status: string; stop_reason: string } | null
  entries: { data: Record<string, string | number | null>; profit: { net_profit: number | null; net_margin: number | null } }[]
  review: { decision: string; reasons: string[]; recorded_days: number; seven_day_net: string | null; recorded_net: string | null; missing_days: string[]; missing_finances: string[]; note: string } | null
}
export interface Keyword { id: number; keyword: string; category: string; origin: string; discovered_at: string }
export interface OpportunityScore {
  score_total: number; confidence_score: number; strategy: Strategy; is_demo: boolean
  dimensions: Record<string, { score: number; weight: number; evidence: string }>
  profit: { net_profit: number | null; net_margin: number | null; missing: string[]; basis: string }
  market: { sample_count: number; price_low: number | null; price_high: number | null; basis: string }
  missing: string[]; warnings: string[]; blockers: string[]; recommendation: string
  confidence_basis: { source_confidence: number; coverage: number; freshness_factor: number }
}
export interface Opportunity {
  id: number; source: string; source_item_id: string; title: string; category: string
  price: string | null; currency: string; url: string | null; observed_at: string; first_observed_at: string
  listing_created_at: string | null; want_count: number | null; view_count: number | null
  score: OpportunityScore; costs: Record<string, string | null>; experiment_status: string | null
  baseline_only?: boolean; observation_count?: number
  suspected_duplicates?: { id: number; title: string; similarity: number; basis: string }[]
}
export interface RadarFilters {
  strategy: Strategy; category: string; q: string; min_confidence: number
  min_margin?: number; source_scope: string; sort: string; pool?: string
}
export interface Ranking { items: Opportunity[]; total: number; page: number; limit: number }
export interface ImportReport { accepted: number; inserted: number; duplicates: number; new_snapshots: number; rejected: number; errors: { line: number; reason: string }[] }
export interface ImportPreview extends ImportReport {
  preview: boolean; total_rows: number; source_counts: Record<string, number>; category_counts: Record<string, number>
  currency_counts: Record<string, number>; missing_counts: Record<string, number>; unknown_profit_rows: number
  older_observations: number; sample_truncated: boolean; note: string
  sample: { line: number; title: string; source: string; category: string; currency: string; price: string | null; action: string }[]
}
export interface ObservationPoint {
  observation_id: number; observed_at: string; price: string | null; want_count: number | null; view_count: number | null
  currency: string; title: string; seller_id: string | null; revision_count: number
  changes: Record<string, number | null>; warnings: string[]
}
export interface ObservationHistory {
  points: ObservationPoint[]; distinct_times: number; total_observations: number; truncated: boolean
  baseline_only: boolean; price_delta: number | null; note: string
}
export interface SyncStatus {
  enabled: boolean; cursors: Record<string, number>; pending: Record<string, number>; last_run_at: string | null
  last_error: string | null; rejected_count: number; interval_seconds: number; external_calls: number
  rejections: { origin: string; row_id: number; reason: string; rejected_at: string }[]
}
export interface ObservedSeller {
  source: string; seller_id: string; observed_items: number; first_observed_at: string; last_observed_at: string; watching: number; note: string
}
export interface SellerItem {
  id: number; title: string; currency: string; source_item_id: string; first_associated_at: string; last_associated_at: string
}
const base = '/api/opportunities'
const json = (method: string, body: unknown) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const radarApi = {
  previewCSV: (content: string): Promise<ImportPreview> => http(`${base}/import/preview`, json('POST', { content })),
  importTemplateUrl: (kind = 'basic') => `${base}/import/template?kind=${encodeURIComponent(kind)}`,
  business: (id: number): Promise<BusinessDossier> => http(`${base}/${id}/business`),
  quotes: (scope: string, page = 1): Promise<{ items: SupplierQuote[]; total: number }> => http(`${base}/suppliers`, { params: { source_scope: scope, page, limit: 50 } }),
  importQuotes: (content: string): Promise<{ accepted: number; inserted: number; rejected: number; errors: { line: number; reason: string }[] }> => http(`${base}/suppliers/import`, json('POST', { content })),
  confirmQuote: (id: number, quote: number, note: string) => http(`${base}/${id}/supplier/${quote}`, json('PUT', { confirmed: true, identity_note: note })),
  experiment: (id: number, config: { start_date: string; status: string; stop_reason: string }) => http(`${base}/${id}/experiment`, json('PUT', config)),
  recordEntry: (id: number, entry: Record<string, unknown>) => http(`${base}/${id}/experiment/entry`, json('PUT', entry)),
  ledgerExportUrl: (id: number) => `${base}/${id}/experiment/export`,
  supplierTemplateUrl: `${base}/suppliers/template`,
  supplierInquiryUrl: (id?: number) => `${base}/suppliers/template?kind=blank${id === undefined ? '' : `&item_id=${id}`}`,
  research: (category = '', keyword = '', source_scope = 'imported'): Promise<MarketEvidence> => http(`${base}/research`, { params: { category, keyword, source_scope } }),
  researchExportUrl: (category: string, keyword: string, source_scope: string) => `${base}/research/export?${new URLSearchParams({ category, keyword, source_scope })}`,
  history: (id: number): Promise<ObservationHistory> => http(`${base}/${id}/history`),
  syncStatus: (): Promise<SyncStatus> => http(`${base}/sync`),
  configureSync: (enabled: boolean): Promise<SyncStatus> => http(`${base}/sync`, json('PUT', { enabled })),
  sync: (): Promise<{ processed: number; new_snapshots: number; rejected: number; paused: boolean }> => http(`${base}/sync/run`, { method: 'POST' }),
  historyDemo: (): Promise<ImportReport> => http(`${base}/demo-history`, { method: 'POST' }),
  sellers: (page = 1, source_scope = 'all', watching_only = false): Promise<{ items: ObservedSeller[]; total: number; note: string }> => http(`${base}/sellers`, { params: { page, source_scope, watching_only } }),
  sellerItems: (seller: ObservedSeller): Promise<{ items: SellerItem[]; total: number }> => http(`${base}/sellers/${encodeURIComponent(seller.source)}/${encodeURIComponent(seller.seller_id)}`),
  watchSeller: (seller: ObservedSeller) => http(`${base}/sellers/${encodeURIComponent(seller.source)}/${encodeURIComponent(seller.seller_id)}/watch`, json('PUT', { watching: !seller.watching, note: seller.note })),
  list: (filters: RadarFilters, page = 1): Promise<Ranking> => http(base, { params: { ...filters, page, limit: 20 } }),
  detail: (id: number, strategy: Strategy): Promise<Opportunity> => http(`${base}/${id}`, { params: { strategy } }),
  categories: (): Promise<Category[]> => http(`${base}/categories`),
  saveCategory: (category: Category): Promise<Category[]> => http(`${base}/categories`, json('PUT', category)),
  keywords: (): Promise<Keyword[]> => http(`${base}/keywords`),
  expand: () => http(`${base}/keywords/expand`, { method: 'POST' }),
  queue: () => http(`${base}/discovery`),
  plan: (budget: number, breadth_ratio: number) => http(`${base}/discovery`, json('POST', { budget, breadth_ratio })),
  demo: (): Promise<ImportReport> => http(`${base}/demo`, { method: 'POST' }),
  importCSV: (content: string): Promise<ImportReport> => http(`${base}/import`, json('POST', { content })),
  importExisting: (): Promise<ImportReport> => http(`${base}/import-existing`, { method: 'POST' }),
  costs: (id: number, costs: Record<string, string | null>) => http(`${base}/${id}/costs`, json('PUT', costs)),
  candidate: (id: number, strategy: Strategy) => http(`${base}/${id}/candidate`, json('POST', { strategy })),
  exportUrl: (filters: RadarFilters) => `${base}/export?${new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))}`,
}
