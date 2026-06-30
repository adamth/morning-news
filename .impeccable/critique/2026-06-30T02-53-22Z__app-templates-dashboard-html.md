---
target: dashboard
total_score: 24
p0_count: 0
p1_count: 3
p2_count: 2
timestamp: 2026-06-30T02-53-22Z
slug: app-templates-dashboard-html
---
Method: ⚠️ DEGRADED: single-context (Assessment A sub-agent unavailable — API limit); Assessment B via sub-agent (B: f219f429-0773-45e2-8864-561760f36582)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Episode generating/failed shown as raw badges only; no in-page progress after Generate now |
| 2 | Match System / Real World | 3 | Message copy is plain; status enums feel internal |
| 3 | User Control and Freedom | 2 | Delete message and Generate now have no confirmation |
| 4 | Consistency and Standards | 3 | List/card pattern consistent; inline style breaks system |
| 5 | Error Prevention | 2 | Destructive actions lack guardrails |
| 6 | Recognition Rather Than Recall | 2 | Feed copy gives no Copied feedback |
| 7 | Flexibility and Efficiency | 2 | Four cards require scroll to reach feed |
| 8 | Aesthetic and Minimalist Design | 2 | Four identical cards; no priority for show status |
| 9 | Error Recovery | 3 | Flash messages work; failed episodes lack guidance |
| 10 | Help and Documentation | 2 | Empty states are one-liners |
| **Total** | | **24/40** | **Acceptable** |

## Anti-Patterns Verdict

LLM: Not generic AI slop — sage palette and serif+sans avoid dark-SaaS clichés. Remaining tell is four same-weight cards (admin scaffold).

Detector: 1 false positive single-font on base.html (CSS path resolution). dashboard.html clean.

Browser: Skipped — no automation.

## Priority Issues

P1 card soup hides confidence check — /impeccable layout
P1 raw status enums — /impeccable clarify
P1 empty states — /impeccable onboard
P2 generate feedback — /impeccable harden
P2 copy confirmation — /impeccable harden
