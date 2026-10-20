import { http } from '@/lib/http'

export type Strategy = 'physical' | 'virtual' | 'resale' | 'blue_ocean'
export interface Category { name: string; parent: string | null; keywords: string[] }
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
  min_margin?: number; source_scope: string; sort: string
}
export interface Ranking { items: Opportunity[]; total: number; page: number; limit: number }
export interface ImportReport { accepted: number; inserted: number; duplicates: number; new_snapshots: number; rejected: number; errors: { line: number; reason: string }[] }
const base = '/api/opportunities'
const json = (method: string, body: unknown) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const radarApi = {
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
