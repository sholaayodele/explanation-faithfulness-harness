# Cost log

Every API run against the ~€10 budget (CLAUDE.md, Models and budget). Updated after every run — append a
row, don't edit past ones. Costs computed from each run's own reported tokens at list price: generator
(`claude-haiku-5-5`) $0.10/1M input, $0.50/1M output; judge (`claude-sonnet-5-5`) $2.00/1M input, $10.00/1M
output.

| date | step | run | model | cases | input tokens | output tokens | cost |
|---|---|---|---|---|---|---|---|
| 2026-10-25 | 6 | Generator v1, full eval set | claude-haiku-5-5 | 200 | 141,856 | 13,522 | $0.0209 |
| 2026-10-25 | 7 | Judge v1, rule checks + LLM judge, full eval set | claude-sonnet-5-5 | 200 | 476,044 | 130,435 | $2.2564 |
| 2026-10-25 | 8 | Judge v1 self-agreement (`--no-cache --repeat 2`) | claude-sonnet-5-5 | 50 × 2 | 237,896 | 69,736 | $1.1732 |
| 2026-10-25 | 8 | Judge v2, adjudicated gold set | claude-sonnet-5-5 | 50 | 139,800 | 28,024 | $0.5598 |
| 2026-10-25 | 8 | Judge v2, fresh hold-out | claude-sonnet-5-5 | 20 | 55,872 | 11,396 | $0.2257 |
| 2026-10-25 | 9 | Judge v2, full eval set (130 newly judged, 70 reused from cache) | claude-sonnet-5-5 | 130 | 363,772 | 77,093 | $1.4985 |
| 2026-10-25 | 10 | Generator v2, full eval set (190 newly generated, 10 reused from cache) | claude-haiku-5-5 | 190 | 593,656 | 11,541 | $0.0651 |
| 2026-10-25 | 10 | Judge v2 on generator v2 outputs, full eval set | claude-sonnet-5-5 | 200 | 557,205 | 97,865 | $2.0931 |

**Running project total: $7.8927** of the ~€10 budget.
