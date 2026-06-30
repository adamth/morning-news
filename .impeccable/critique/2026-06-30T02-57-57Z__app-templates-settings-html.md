---
target: settings
total_score: 22
p0_count: 0
p1_count: 3
p2_count: 2
timestamp: 2026-06-30T02-57-57Z
slug: app-templates-settings-html
---
Method: ⚠️ DEGRADED: single-context (Assessment A sub-agent unavailable — API limit); Assessment B via sub-agent (B: 4fe4b6c5-3c08-43b9-9fd6-fccfc53c5f78)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Location/model autocomplete hints are good; saves only confirm via redirect flash |
| 2 | Match System / Real World | 2 | ElevenLabs, OpenRouter, CalDAV, Google News edition IDs — operator jargon |
| 3 | User Control and Freedom | 2 | Chip/source deletes lack confirm; one mega-form makes partial experimentation risky |
| 4 | Consistency and Standards | 2 | Dashboard recently restructured; Settings still uses old card-soup + inline styles |
| 5 | Error Prevention | 2 | Location pick enforced server-side (good); timezone is free text; silent chip deletes |
| 6 | Recognition Rather Than Recall | 2 | 18 category checkboxes at once; advanced knobs beside daily essentials |
| 7 | Flexibility and Efficiency | 2 | Long scroll, no section jump links, no keyboard accelerators |
| 8 | Aesthetic and Minimalist Design | 2 | One card holds ~25 fields across three `<hr>` sections — density without hierarchy |
| 9 | Error Recovery | 3 | Redirect `?err=` flashes work; model/location hints explain failures |
| 10 | Help and Documentation | 2 | Field hints exist but assume technical literacy; no first-run path |
| **Total** | | **22/40** | **Acceptable leaning poor — configure-once promise undermined by overwhelm** |

## Anti-Patterns Verdict

**LLM:** Visual tokens match the kitchen-radio system (sage, serif headings, flat cards). The slop signal here is **information architecture**, not palette: a single mega-form card with internal `<hr>` section breaks, plus four sibling cards — the same pattern dashboard just escaped. Reads as "admin settings page," not "set your radio dial once."

**Deterministic scan:** 1 finding on `base.html` (`single-font`) — false positive (CSS path resolution). `settings.html`: clean.

**Browser:** Skipped — no automation.

## Overall Impression

Settings is where PRODUCT.md's "configure once, trust daily" lives or dies. The fields are comprehensive, but the page treats a household user like a pipeline operator: eighteen story categories, model IDs, and charset limits share one scroll with "what time should the show run?" Dashboard got the hierarchy fix; Settings is still the long intimidating form.

## What's Working

1. **Location autocomplete with confirmation gate** — pick-from-list + hidden lat/long prevents bad geocoding; status hint explains state clearly.
2. **Excluded topics as chips** — scannable, household-friendly pattern for "don't talk about war."
3. **Shared-household subtitle** — sets expectation that changes affect everyone (rare clarity on a settings page).

## Priority Issues

### [P1] Mega-form mixes essentials with operator controls
- Schedule, location, calendar, 18 categories, article char limits, voice model, OpenRouter, podcast metadata, weather toggle — one `<form>`, one Save.
- **Fix:** Split into stepped sections: "Daily show" (time, location, calendar, weather) → "Voice & intro" → "Fine tuning" (collapsed/advanced). Separate save per section or sticky save bar.
- → `/impeccable layout app/templates/settings.html`

### [P1] Story priorities grid is cognitive overload
- 18 checkboxes in `category-grid` exceeds working-memory limits for casual users.
- **Fix:** Show 4–6 recommended defaults + "More topics" disclosure; or grouped selects (News / Life / Sports).
- → `/impeccable distill app/templates/settings.html`

### [P1] Vendor jargon without plain-language framing
- "ElevenLabs voice", "OpenRouter model", "CalDAV or public .ics", "Google News edition: en-US / US / US:en".
- **Fix:** Lead with outcome labels ("Narrator voice", "Script writer", "Family calendar link"); hide edition IDs behind "Advanced news region."
- → `/impeccable clarify app/templates/settings.html`

### [P2] Five-card stack inconsistent with dashboard IA
- Schedule mega-card + Excluded + Intro + Sources + Users — equal visual weight, long scroll.
- **Fix:** Collapse secondary cards (`<details>`) like dashboard messages; elevate "Daily show" hero.
- → `/impeccable layout app/templates/settings.html`

### [P2] Destructive actions lack guards
- Source delete, preference chip ×, no confirm (unlike dashboard message delete).
- → `/impeccable harden app/templates/settings.html`

## Persona Red Flags

**Alex:** 800px+ of fields before reaching Users. Wants section anchors or collapsed advanced panel. Chip delete is one click — accidental removal of "politics" exclusion.

**Jordan:** "OpenRouter model" and "eleven_v3" mean nothing. Won't know CalDAV vs .ics. Eighteen equal checkboxes — paralysis. Where to start vs what's optional?

**Sam:** 18-checkbox grid is tedious by keyboard. Chip remove buttons are `×` with `title="Remove"` only — weak accessible name. Inline `style="width:auto"` checkboxes may have inconsistent focus targets.

**Morgan (household partner):** Subtitle says shared, but no callout on which changes affect the shared feed vs personal login. User management at bottom feels like admin console, not "invite your partner."

## Minor Observations

- Inline `style=` on `<hr>`, margins, checkbox widths — breaks spacing system used on dashboard.
- Scripts injected in `{% block content %}` instead of `{% block scripts %}`.
- `max_article_length` in characters — meaningless unit for household users.
- Timezone field editable after auto-set — good for power users, confusing if it drifts from location.

## Questions to Consider

- What if a new install saw only three questions: when, where, and who's talking?
- Do 18 category checkboxes earn their space, or should defaults carry most households?
- Should "Advanced" be a deliberate opt-in, not the default scroll experience?
