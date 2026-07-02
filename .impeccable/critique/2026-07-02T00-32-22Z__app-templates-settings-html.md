---
target: the settings page
total_score: 23
p0_count: 1
p1_count: 2
timestamp: 2026-07-02T00-32-22Z
slug: app-templates-settings-html
---
Method: dual-agent (A: cc91a761-9dd0-4d73-bd3e-7fca53d692ce · B: 5fbeed54-c296-4b45-a16d-7cea2351bc3d)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | The dedicated status surface 500s; no dirty-state indication across 5 separate forms per page |
| 2 | Match System / Real World | 3 | Copy is superb ("Your town", "Build time"), but Time zone expects raw IANA strings and Writing model expects `x-ai/grok-4.3` |
| 3 | User Control and Freedom | 2 | No undo/confirm on Remove/Delete; unsaved edits silently lost when another section's Save is pressed |
| 4 | Consistency and Standards | 3 | Four different remove idioms (table "Remove", "Delete feed", chip "×", "Delete saved key" checkbox); "Save stock settings" is btn-sm while sibling saves are full-size |
| 5 | Error Prevention | 2 | Leave-blank-to-keep-key is excellent; destructive actions unconfirmed, timezone free-text unvalidated |
| 6 | Recognition Rather Than Recall | 3 | Good cross-links; but stock watch spans three tabs with nothing explaining why |
| 7 | Flexibility and Efficiency | 1 | No accelerators of any kind; acceptable at this product scale, but nothing here |
| 8 | Aesthetic and Minimalist Design | 3 | Calm and uncluttered; undermined by monochrome-purple hierarchy and a shipped NewsData.io field that "does not use this yet" |
| 9 | Error Recovery | 1 | The one real error encountered is a raw white "Internal Server Error" with no chrome, no way back |
| 10 | Help and Documentation | 3 | Inline help genuinely good (per-provider calendar instructions, "Get a key" links); no help destination beyond that |
| **Total** | | **23/40** | **Acceptable — significant improvements needed** |

## Anti-Patterns Verdict

**LLM assessment**: Passes the surface slop test, fails the project's own brief. No absolute bans triggered: no side-stripes, no gradient text, no hero metrics, no card grids, no eyebrow/numbered scaffolding, no text overflow at 390px. Copy is conspicuously human — the strongest anti-slop signal. But the palette is the category reflex: a vivid violet accent (`--color-accent: oklch(58% 0.24 285)`) on lavender-tinted ground — the generic AI-SaaS purple admin panel — while DESIGN.md's north star is restrained sage at ≤10% of any screen. The accent floods headings, dividers, chips, table headers, tags, links, buttons, and the active tab. Secondary tell: `.section` carries backdrop-blur + shadow against a "flat by default" system, decorating nothing.

**Deterministic scan**: 1 CLI finding — "single-font" in `app/templates/base.html`, judged a false positive (Literata + Work Sans are both loaded). Browser detector, injected on all four tabs: 2 real findings on /settings (cramped table padding, 92-char line length), Advanced and Connections clean, and /settings/status could not be scanned because it returns a 500 (`NameError: get_health_report` undefined in `app/routes/ui.py:282`).

**Visual overlays**: Injection succeeded on the three working tabs; overlays highlighted the cramped stock-table padding and over-long hint line length on /settings. The overlay server was stopped after evidence collection.

## Overall Impression

The words are right and the pixels are wrong. This is one of the most human-sounding settings surfaces I've reviewed — "Your town", "Build time", "usually set once and left alone" — and the credential UX on Connections is genuinely well designed. But the page a new user lands on never tells them the one thing they must do first (add two required keys on Connections), the reassurance tab crashes with a raw 500, and the violet-everywhere palette flattens hierarchy while contradicting the sage system the project wrote for itself. The single biggest opportunity: make the first-run path explicit — a new user should know in five seconds what to do first and whether the show will build tomorrow.

## What's Working

1. **The copy is the personality.** "Your town", "Who can sign in", "No extra feeds — local headlines from your town are enough for most households." This is the kitchen-radio voice PRODUCT.md asked for, and the per-provider calendar instructions (Google → "Integrate calendar", iCloud → "Public Calendar") are better than most commercial products ship.
2. **Credential state design on Connections.** Green "Key saved" dot, "Server config" chip, leave-blank-to-keep placeholder, explicit "Delete saved key" checkbox — prevents accidental overwrite and accidental deletion without a single modal.
3. **Required/Optional tagging with a recommended path.** "Required" on Narration and Episode writing, "Good first choice" on OpenRouter, "Skip unless…" on extras gives a first-timer a walkable spine through the scariest tab.

## Priority Issues

1. **[P0] System status tab is a raw 500.** `/settings/status` crashes (`NameError: get_health_report` in `app/routes/ui.py:282`); the user sees an unstyled white "Internal Server Error". This is the reassurance surface for a product whose promise is "trust the daily pipeline" — it's linked from the nav badge and from Advanced's model-failure hint, and a new user will assume they broke something. **Fix**: repair the import/name; add a styled error page (site chrome + plain-language message + link back). **Suggested command**: /impeccable harden.
2. **[P1] First-run sequencing is inverted.** The landing tab (Basic) never tells a new user that nothing works until ElevenLabs + one writing key exist on Connections. Jordan fills in town and schedule, saves, believes setup is done, and the show silently can't build. **Fix**: when required keys are missing, show a setup banner or mini-checklist at the top of Basic: "Before your first episode: add 2 required keys on Connections." **Suggested command**: /impeccable onboard.
3. **[P1] Per-section saves with no dirty-state.** Basic has five independent forms, Advanced four+; sections look continuous but save independently. Edit "Your town" and tick a stock checkbox, press one Save, silently lose the other. **Fix**: one form + one sticky save per tab, or visible per-section dirty indicators plus an unsaved-changes cue. **Suggested command**: /impeccable harden.
4. **[P2] Accent contradicts the design system and floods the page.** Violet instead of DESIGN.md's sage, applied to headings, dividers, chips, table headers, tags, and CTAs alike — erasing the product's one distinctive visual idea and flattening hierarchy. **Fix**: retoken to sage; return `.settings-heading` to ink; reserve accent for primary CTA, active tab, focus, and positive status per the ≤10% rule. **Suggested command**: /impeccable colorize, then /impeccable quieter.
5. **[P2] Instructional microcopy fails contrast.** Placeholders carry real instructions ("Leave blank to keep your saved key", "Start typing, then pick from the list") at 3.27:1; the "Optional" tag is 3.95:1, green "Key saved" 3.96:1, accent links in hints 4.34:1. PRODUCT.md names legibility in varied kitchen lighting as the accessibility priority, and these strings are load-bearing for new users. **Fix**: darken placeholder mix to ≥4.5:1, bump tag/status colors one step, move leave-blank behavior into the visible hint. **Suggested command**: /impeccable audit → /impeccable polish.

## Persona Red Flags

**Jordan (first-timer)**: Lands on Basic with no signal that Connections is a prerequisite — will "finish" setup without a working show. "Basic / Advanced / Connections" are container labels; Jordan learns what each holds only by clicking all four. The Time zone field expects `Australia/Brisbane` IANA syntax; typing "AEST" breaks the schedule with no validation. "Writing model" free-text (`x-ai/grok-4.3`) is pure jargon, and its failure hint routes to the 500 status page. Saved by: "Good first choice" tag, Required/Optional tags, calendar walkthrough.

**Sam (accessibility)**: Six identical "Remove" buttons in the stock table with no accessible ticker name; four identical "Get a key" links on Connections. (Chips do this right — `aria-label="Remove politics from skip list"` — the table should match.) Placeholder-only instructions at 3.27:1 vanish on focus. Otherwise decent: visible focus rings, `aria-current` on tabs, sr-only labels on table inputs, status badges pair text with color.

**The non-technical partner at the breakfast table** (from PRODUCT.md): Their concerns (story mix, topics to skip, build time) are correctly on Basic. But their own login lives under Advanced → "Who can sign in", classifying a household-people concept as fine-tuning. Jargon islands on their path: "^GSPC (S&P 500)" ticker syntax, "Server config" chips, the Docker/.env footnote.

## Minor Observations

- "System status" orphans onto a second tab row at 390px; consider shortening to "Status".
- The count tag "6" beside "Stock watch" has no unit — 6 what?
- "Save stock settings" uses btn-sm while every sibling save is full-size.
- Advanced's lead sentence lists "Voice, length, feeds, household logins" in a different order than the page presents them.
- `settings-*` and `connections-*` CSS component families are near-duplicate copies — they will drift.
- `.section`'s backdrop-blur does nothing; the sticky topbar's blur is the only earned one.
- The NewsData.io field ships as UI for a feature that doesn't exist ("Reserved for a future local-news feature").
- Basic runs ~3,800px tall on mobile with no in-page section navigation.
- Detector: stock table padding is cramped; hint text on /settings runs to 92 characters per line (cap prose at 65–75ch).

## Questions to Consider

1. What if Settings opened as a five-step setup checklist for the first week ("Keys ✓ · Town ✓ · Schedule ✓ · Voice — · Listen —") and only then dissolved into tabs? The tabs serve the maintainer; the checklist serves the first morning.
2. If sage is the brand's one color, what would this page feel like if the only saturated element were the single button that matters on each tab — and every heading went back to ink?
3. Does a two-person household need a "Basic vs Advanced" taxonomy at all, or is the honest split "Your show" (what it says, when, where) vs "The plumbing" (keys, feeds, logins, health)?
