# Codex start prompt — copy into Codex Cloud/IDE

Use existing repository `dong520520/ai-goofish-monitor`.
Checkout `codex/p2-oss-integration-20261021`, which is branched from P1 (`feat/opportunity-observation-sync`) and contains the OSS integration handoff.

Read in this order:
1. `AGENTS.md`
2. `docs/OPPORTUNITY_P0.md` and `docs/OPPORTUNITY_P1.md`
3. `docs/codex/OSS_SOURCES_LOCK.md`
4. `docs/codex/P2_OSS_INTEGRATION_HANDOFF.md`

**Do not create a new project, do not copy whole GitHub repos, do not rewrite the P0/P1 branches.**
Implement P2A now: trustworthy OFFLINE multi-category discovery/keyword cohort analysis using the existing SQLite and existing service/API/Vue structure, with category coverage, dedup, provenance, confidence, ranking evidence and full regression tests. Keep live platform collection off. P2B supplier+experiment after P2A passes.

Review the open stacked PRs #1 and #2; target PR base `feat/opportunity-observation-sync`. Follow the P2 handoff acceptance tests. Run pytest and frontend build and report actual results, with a draft PR/screenshot if available. Start coding instead of merely drafting another plan.
