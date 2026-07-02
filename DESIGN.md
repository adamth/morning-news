<!-- SEED: re-run /impeccable document once there's code to capture the actual tokens and components. -->
---
name: Morning News
description: Warm household utility for configuring a daily kitchen-table podcast
---

# Design System: Morning News

## 1. Overview

**Creative North Star: "The Kitchen Radio"**

Morning News is a domestic configuration surface — not a dashboard, not a landing page. The visual system should feel like setting a radio dial at breakfast: calm, legible, warm without whimsy. Restrained color, editorial typography, and flat surfaces that prioritize trust over spectacle.

The UI serves a household ritual. Density stays moderate; hierarchy is obvious; nothing shouts for attention. References: NPR One's quiet confidence, Calm's unhurried clarity, and the physical presence of a vintage kitchen radio — tactile, familiar, always there.

**Key Characteristics:**
- Restrained palette: tinted neutrals with sage as the sole accent, used sparingly
- Serif + sans pairing for editorial warmth without magazine pretension
- Flat-by-default surfaces; depth through tone, not shadow theater
- Motion limited to state feedback — no scroll choreography or entrance fanfare
- Explicit rejection of startup marketing scaffolding and generic dark-SaaS monoculture

## 2. Colors

**The Restrained Rule.** Tinted neutrals carry the interface. Sage accent appears on ≤10% of any screen — primary actions, active nav, focus rings, success-adjacent highlights. Its rarity is the point.

### Primary
- **Sage** (`oklch(50% 0.09 152)`, strong `oklch(42% 0.1 152)`, soft `oklch(93% 0.03 152)`): Accent for primary buttons, active navigation, focus states, and positive status. Muted green — garden and seasonal, not neon eco-brand.

### Neutral
- **Ground** (`oklch(97.3% 0.008 150)`): Page background. Sage-tinted neutral at low chroma — the tint is felt, not seen.
- **Surface** (`oklch(99.3% 0.004 150)`): Cards and elevated panels. One step above ground; tonal layering, not shadow.
- **Ink** (`oklch(25% 0.02 155)`): Body text. 14.7:1 against ground.
- **Muted ink** (`oklch(46% 0.025 152)`): Secondary labels, hints, timestamps. 6.5:1 against ground — readable, sage-hued, not generic gray.
- **Border** (`oklch(87% 0.015 150)`) and **emphasis** (`oklch(94.5% 0.018 150)`): hairlines and table-header/nested-panel washes.

### Functional secondaries
Coral (`oklch(52% 0.14 32)`) for required/warning notes, sky (`oklch(50% 0.05 230)`) for optional/informational tags, danger (`oklch(50% 0.18 25)`) for destructive actions and failures. All subdued; none decorative.

### Named Rules
**The No-Cream Rule.** Warmth lives in accent, typography, and copy — not in a saturated near-white body background. Avoid the 2026 cream/sand/paper band unless the brief explicitly demands it.

**The One Voice Rule.** Sage is the only chromatic accent. Status colors (error, warning) may exist but stay functional and subdued.

## 3. Typography

**Display Font:** [font pairing to be chosen at implementation — serif display]
**Body Font:** [font pairing to be chosen at implementation — humanist sans]

**Character:** Editorial warmth without newsroom austerity. Serif for page titles and section headers; sans for forms, lists, labels, and UI chrome. Pair on contrast axis — not two similar sans-serifs.

### Hierarchy
- **Display** (serif, clamp for h1, tight line-height): Page titles — Dashboard, Settings. `text-wrap: balance`.
- **Headline** (serif or semi-bold sans, ~18–22px): Section headers within cards.
- **Title** (sans, 600 weight, ~14–16px): Form labels, list item titles.
- **Body** (sans, 400 weight, ~14–16px, 1.55 line-height): Prose, hints, list content. Max ~65–75ch where long-form appears.
- **Label** (sans, 600, ~12–13px): Badges, meta timestamps, chip text.

### Named Rules
**The Contrast Pair Rule.** Serif display + sans body. Never two geometric sans-serifs or two humanist sans-serifs in the same hierarchy.

## 4. Elevation

Flat by default. Depth is conveyed through tonal layering (ground → surface → surface-2) and 1px borders, not drop shadows. Shadows, if used at all, are soft and ambient — reserved for dropdowns, autocomplete panels, and sticky chrome. No card-shadow soup.

### Named Rules
**The Flat-By-Default Rule.** Cards sit on surface tone with a hairline border. Shadows appear only when an element must float above scroll content (suggestions dropdown, sticky topbar).

## 5. Components

[Components to be documented after implementation. Re-run `/impeccable document` in scan mode once tokens and patterns exist in code.]

Expected primitives based on current app: topbar navigation, form inputs with location autocomplete, primary/secondary/danger buttons, status badges, list rows, flash messages, chips, episode cards.

## 6. Do's and Don'ts

### Do:
- **Do** use sage sparingly — primary CTA, active nav, focus ring, ready-state badge.
- **Do** keep body text high-contrast; bump ink toward dark when in doubt.
- **Do** respect `prefers-reduced-motion: reduce` — instant or crossfade only.
- **Do** design for a laptop at the breakfast table: generous tap targets on buttons, readable at arm's length.

### Don't:
- **Don't** use startup landing page clichés: hero metrics, gradient text, eyebrow labels on every section, SaaS marketing scaffolding.
- **Don't** default to generic dark dashboard monoculture (blue accent on charcoal, system-font card grid) unless deliberately chosen for a specific surface.
- **Don't** clone consumer podcast apps — this is configuration, not listening.
- **Don't** use side-stripe borders, gradient text, or glassmorphism as decoration.
- **Don't** put an uppercase tracked eyebrow above every section.
- **Don't** animate layout properties or gate content visibility on entrance animations.
