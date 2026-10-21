# OSS source lock and license disposition — 2026-10-21

Source codes/revisions were inspected through connected GitHub; these are integration references, not claims of upstream correctness.

| Upstream | Pinned revision | License evidence | Use |
|---|---|---|---|
| [Usagi-org/ai-goofish-monitor](https://github.com/Usagi-org/ai-goofish-monitor) | 77f8d75869acd65f9dba72731b95c7c49ea67bdf | MIT LICENSE confirmed | Already reused through existing fork; DO NOT reimport/rebuild |
| [122267881/xianyu-demand-operator](https://github.com/122267881/xianyu-demand-operator) | d8641d27053f360c7b9b70b0f1e9adedd0e03d82 | Repository LICENSE contains MIT; GitHub license metadata said NOASSERTION | Vendored original scoring rubric + LICENSE as third-party methodological material; preserve attribution |
| [weiyinerzui/xianyu-ops](https://github.com/weiyinerzui/xianyu-ops) | 6c4b2aaba0cc83a84f026664df2c05a19bcfd933 | No stand-alone LICENSE confirmed | Reference `scorer.py`, `demand.py` concepts only; do not copy code |
| [djzhhil/xianyu-radar](https://github.com/djzhhil/xianyu-radar) | c4dd572c440f3a59e1ac44fa477556a010187c2c | No stand-alone LICENSE confirmed | Reference first-baseline, incomplete-pagination and anomaly guards only; do not copy code |
| [xiaolu-ai26/XY-Agent](https://github.com/xiaolu-ai26/XY-Agent) | ea76499e17bc1e95ddd2d97085e1dccc4787ae48 | README claims MIT, but standalone LICENSE file not verified | High-level workflow reference only, no code copy |

## Why no monorepo merge

- Existing code already implements FastAPI, Vue 3, SQLite, AI analysis, tasks, local data sync, candidate/ranking UI.
- Other projects sometimes duplicate services with divergent runtime/DB/credential assumptions, leading to fragile merges.
- The highest-value integration is business logic and **clearly licensed materials**, plus direct native additions in the fork.
- Do not copy content or install runtime imports from repositories without a confirmed compatible license.
- The included source scorecard is a DESIGN INPUT, NOT the currently implemented or validated production model.
- For data rights: a project showing browser automation does not imply the platform authorizes extraction. Build the new selection/analysis pipeline on permitted inputs and existing local data.

## Observed anti-patterns to test against

- `xianyu-ops` basic scorer uses fixed thresholds on count of samples and infers demand from available wants. For arbitrary category samples, these count assumptions are not universal.
- `xianyu-ops` demand report uses `last_seen` to calculate "fresh" counts, which is not actual listing publication date.
- `xianyu-radar` documents past false new-listing event counts when a first scan is treated as later scan; incomplete pages and dramatic count drops need sanity checks.
- Never conflate observed sampled prices, want/view signals, disappearance or sample count with sales, turnover or full marketplace inventory.

Third-party copied resources:
- `third_party/xianyu-demand-operator/references/SCORING_MODEL.md`
- `third_party/xianyu-demand-operator/LICENSE`
- `third_party/xianyu-demand-operator/UPSTREAM.md`

Retain the original upstream source attribution and license text when copying or modifying the source material.
