# Codex P2: integrate OSS ideas into the existing full-category opportunity radar

## Mission and starting point

Build upon **this exact existing repository**, not a greenfield project: https://github.com/dong520520/ai-goofish-monitor

- Base of this task: `feat/opportunity-observation-sync` at `6bb747e1aa8db13f5a01c9488387fc1c0581d2f8`
- Handoff branch: `codex/p2-oss-integration-20261021`
- PR #1 (`feat/opportunity-engine-mvp` -> `master`) already contains CSV import, four strategies, six-axis scores, confidence, ranking UI, category/keyword configuration and bounded offline discovery.
- PR #2 (`feat/opportunity-observation-sync` -> `feat/opportunity-engine-mvp`) already contains continuous LOCAL sync from the EXISTING SQLite, source observations, historical price/interest differences, observed seller associations.
- Preserve these stacked PRs. Do not replace the monitoring stack, create a second backend, or claim PR #1/#2 are merged.
- Existing conventions: root `AGENTS.md`, `docs/OPPORTUNITY_P0.md`, `docs/OPPORTUNITY_P1.md`.

## Upstream integration decision

Read `docs/codex/OSS_SOURCES_LOCK.md` and `third_party/xianyu-demand-operator/` first.
Use **selective integration**, not wholesale project merges:
1. Usagi-org/ai-goofish-monitor: already forked and used as FastAPI/Vue/SQLite/AI/task infrastructure. Keep intact.
2. 122267881/xianyu-demand-operator: MIT-licensed rubric vendored as a methodological reference with LICENSE and provenance; implement useful verified-demand, supply-check and 7-day evaluation ideas in native modules. Do NOT replace existing six-axis scoring silently.
3. weiyinerzui/xianyu-ops: market price quantiles, keyword evidence and missing-data reporting are DESIGN INSPIRATION ONLY (no confirmed standalone source license; do not copy code). Existing scorer heuristics and 'last_seen' do not establish actual new listings.
4. djzhhil/xianyu-radar: baseline and incomplete-snapshot protections are DESIGN INSPIRATION ONLY (no confirmed standalone source license; do not copy code). Preserve current behavior and strengthen tests.
5. xiaolu-ai26/XY-Agent: no validated standalone LICENSE at time of handoff. Workflow reference only; do not copy code.
No unauthorized automatic data collection. Do not implement captcha/security bypass, proxy/account rotation to defeat restrictions, credential harvesting, scraping around access denials, or unapproved actions on other users' accounts. Follow platform permissions; authentication challenge/rate-limit/denial means stop and hand off to human. Keep network operations OFF in default tests.

## Reuse map in THIS repository

Existing entry points and contracts (inspect current branch before editing):
- `src/app.py` and `src/api/routes/opportunities.py`: FastAPI, authenticated under existing Web login.
- `src/services/opportunity_service.py`: CSV import, `expand_keywords()`, `queue()`, existing SQLite projection.
- `src/services/opportunity_sync_service.py`: local scheduled sync; do not add more platform requests.
- `src/domain/models/opportunity.py` and `src/domain/opportunity_scoring.py`: existing typed domain and 4 scoring modes.
- `src/domain/opportunity_history.py`, `src/infrastructure/persistence/opportunity_repository.py`, `src/infrastructure/persistence/opportunity_schema.py`: observation/history storage and schema.
- `web-ui/src/views/OpportunitiesView.vue` and `web-ui/src/api/opportunities.ts`: existing UI. Extend, don't recreate app.
- `tests/unit/test_opportunity_scoring.py`, `tests/integration/test_api_opportunities.py`, `tests/integration/test_opportunity_sync.py`: required regression patterns.

## P2A: full-category OFFLINE discovery and credible opportunity ranking (implement first)

1. Inspect existing `categories`, `keyword_seeds`, `discovery_jobs`, `opportunity_items`, `opportunity_observations` and APIs. Build on schema with additive, idempotent migrations. Never delete or relabel user data. No second DB.
2. Create bounded multi-category discovery planner around existing `expand_keywords()` and `queue()`: configurable breadth/depth ratio (keep existing current behavior unless changed by explicit user config), fair category coverage and exploration quotas, keyword dedup/normalization, traceable seed -> derived keyword -> candidate evidence. Do not run an unauthorized external collector; queue tasks as `pending_manual` or export for permitted data sources. Queue reruns must be idempotent.
3. Build MARKET (keyword/category cohort) evidence separate from ITEM score: observed sample size, price quantiles p25/p50/p75, matching currency, condition/model comparability if known, distinct stable sellers, interest-signal coverage and observation timestamps. Distinguish sample counts from total-market counts. Do not invent demand, listing dates or sales. Do not mistake first_seen/last_seen for real listing date.
4. Add ranking evidence and explanations: why selected, why rejected, provenance, missing data, confidence, category coverage. Synthetic_demo source must not leak into actual-market evaluation. Unknown numeric fields stay NULL, not zero.
5. Keep all four existing strategies (`physical`, `virtual`, `resale`, `blue_ocean`); risk hard-blocked products cannot become priority candidates. Score in deterministic Python; LLM optional for narrative only, never factual quantities.
6. Add minimal authenticated API and Vue dashboard extension, preserving old endpoints and responsive UI. Prefer existing service/domain/repository patterns; no new frontend framework.
7. Expose CSV input and CSV export of evidence with formula-injection protection; protect import sizes, task budget, DB transactions and query bounds.

Deliver P2A as real code + tests, not docs-only. First acceptance milestone: with purely synthetic imported examples and no account/AI key, user can click through category discovery -> evidence cohort -> confidence-aware opportunity rank -> candidate shortlist.

## P2B: supplier quotes, honest net margin, 7-day experiment (after P2A green)

1. Add explicit supplier quote import (CSV example; provenance, timestamp, SKU, purchase cost, currency, shipping, lead time, MOQ and confidence/verification notes). Supplier data is user-provided, not auto-verified.
2. Link supplier quotes to candidates with manual confirmation. No blind fuzzy merge on title; maintain distinct product identity, SKU, specification, condition, currency.
3. Extend existing cost assumptions rather than introducing a competing pricing engine. Missing purchase, delivery, platform fees or expected loss means profit remains unknown; verified zero is allowed. Use Decimal and the currently documented pricing fields. Show per-sale net profit + net margin and input provenance.
4. Extend existing `experiments` from candidate tagging to a manual, own-business 7-day test ledger: exposure (if available), inquiry, orders, refunds, realized net, test status, stop reason. Never infer platform sales from item disappearance or want/view counts.
5. Output review: continue/test/fill-evidence/stop, backed by recorded own-business results. Keep purchases, posting, chat and fulfilment out of scope.

## Test & quality gates

- Before work: capture current baseline using `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest` (on Windows use local `--basetemp` per P0 docs), plus `cd web-ui && npm ci && npm run build`.
- New cases: duplicate CSV; missing vs literal 0; stale observation order; duplicate snapshot; first scan baseline; incomplete batch; ambiguous seller IDs; multi-currency separation; demo-vs-real isolation; category starvation with finite budget; identical keyword reruns; supplier quote ambiguity; refund/profit sensitivity; authorization on new endpoints; CSV injection and boundaries.
- Do not make live platform requests in automated tests. Use synthetic fixtures only, marked as synthetic.
- Preserve original task management, notifications, login, status, price history and original monitoring.
- Add schema migration/back-up instructions. Never commit Cookie, credentials, .env or actual user listings.
- Document actual test command results and limitations. Do not claim a command or deployment passed without running it.

## Deliverables / definition of done

1. P2A feature code + unit/integration tests + Vue integration and new documentation `docs/OPPORTUNITY_P2.md`.
2. P2B supplier and experiment iteration in separate focused commits or follow-up PR, after P2A passes.
3. Update existing README + original AGENTS.md only as necessary and preserve existing structure.
4. PR against `feat/opportunity-observation-sync` (stacked until #1/#2 are merged), list changed modules and genuine test outcomes, add screenshots for UI changes.
5. First Codex reply: state inspected files, current P0/P1 baseline, integration plan, and proceed to IMPLEMENT P2A (do not stop after planning).

User's top priority is full-category PRODUCT RESEARCH: automatic candidate discovery from permitted inputs, reliable opportunity evidence, margin verification, then test feedback. Automated customer service and posting are **out of scope**.
