---
name: Morning News
description: Warm household utility for configuring a daily kitchen-table podcast
---

# Design System: Morning News

## 1. Overview

**Creative North Star: "The Kitchen Radio"**

Morning News is a domestic configuration surface and a small episode shelf — not a
dashboard, not a landing page. The visual system should feel like setting a radio dial at
breakfast: calm, legible, warm without whimsy. Restrained color, flat surfaces, and one
loud thing per screen.

The structural language is borrowed from [syntax.fm](https://syntax.fm): pill navigation
with a solid-filled active state, big rounded episode cards carrying an oversized ghosted
episode number that bleeds off the right edge, heavy monospace display type, and a sticky
bottom player that any play button on the page feeds. The palette is not borrowed — it
stays in the tinted-neutral, single-sage-accent register below, on a light ground.

**Key Characteristics:**
- Restrained palette: tinted neutrals with sage as the sole accent, used sparingly
- Monospace display + humanist sans body: mechanical headlines, readable forms
- Flat-by-default surfaces with 1.5px hairlines; depth through tone, not shadow theater
- Pills for anything navigational; rounded rectangles for anything containing content
- Motion limited to state feedback — no scroll choreography or entrance fanfare

## 2. Colors

**The Restrained Rule.** Tinted neutrals carry the interface. Sage appears on ≤10% of any
screen — primary actions, active nav, focus rings, play buttons, ready-state badges. Its
rarity is the point.

### Primary
- **Sage** (`oklch(50% 0.09 152)`, strong `oklch(42% 0.1 152)`, soft `oklch(93% 0.03 152)`):
  Accent for primary buttons, active navigation, focus states, and positive status.
- **Sage ghost** (`oklch(89% 0.055 152)`): reserved for the oversized episode number.
  Strong enough to read as a graphic, weak enough not to compete with the title.

### Neutral
- **Ground** (`oklch(97.3% 0.008 150)`): Page background. Sage-tinted at low chroma — the
  tint is felt, not seen.
- **Surface** (`oklch(99.3% 0.004 150)`): Cards and elevated panels. One step above ground.
- **Ink** (`oklch(25% 0.02 155)`): Body and display text. 14.7:1 against ground.
- **Muted ink** (`oklch(46% 0.025 152)`): Secondary labels, hints, timestamps. 6.5:1.
- **Border** (`oklch(87% 0.015 150)`) and **emphasis** (`oklch(94.5% 0.018 150)`): hairlines
  and table-header / nested-panel washes.

### Functional secondaries
Coral (`oklch(52% 0.14 32)`) for required/warning notes, sky (`oklch(50% 0.05 230)`) for
optional/informational tags, danger (`oklch(50% 0.18 25)`) for destructive actions and
failures. All subdued; none decorative.

### Named Rules
**The No-Cream Rule.** Warmth lives in accent, typography, and copy — not in a saturated
near-white body background.

**The One Voice Rule.** Sage is the only chromatic accent. Status colors may exist but stay
functional and subdued.

## 3. Typography

**Display Font:** JetBrains Mono (700 / 800), tracked tight (`-0.02em` to `-0.07em`)
**Body Font:** Work Sans (400 / 500 / 600)

**Character:** Mechanical headlines against readable body copy. Monospace carries every
title, nav pill, button label, and section heading; the sans carries prose, form fields,
hints, and list content. The pairing is the contrast — never set body copy in the mono.

### Hierarchy
- **Display** (mono 700, `text-3xl`→`4xl`, `-0.04em`): Page titles. `text-wrap: balance`.
- **Episode title** (mono 700, `text-2xl`→`3xl`, `-0.035em`, max `34ch`): The hero headline.
  The width cap keeps it clear of the ghosted number.
- **Section title** (mono 700, `text-xl`, `-0.03em`): Settings sections, card headings.
- **Group title** (mono 700, `text-base`, `-0.02em`): Subsections inside a settings section.
- **Body** (sans 400, 15–16px, 1.55 line-height): Prose, hints, list content. Max ~58–68ch.
- **Label** (sans 600, 12–14px): Form labels, badges, meta, chips.
- **Eyebrow** (sans 600, `text-xs`, `0.14em`, uppercase): Used once, on the hero only.

### Named Rules
**The Contrast Pair Rule.** Monospace display + humanist sans body. Never set a paragraph
in the display font, and never set a title in the body font.

**The One Eyebrow Rule.** At most one uppercase tracked eyebrow per page, and only where it
labels the page's single most important object ("TODAY'S SHOW").

## 4. Elevation

Flat by default. Depth comes from tonal layering (ground → surface → emphasis) and 1.5px
borders, not drop shadows. Shadows are reserved for elements that must float above scroll
content: the autocomplete dropdown, toasts, the sticky topbar and player (which use
`backdrop-blur` and a translucent ground rather than a cast shadow).

### Named Rules
**The Flat-By-Default Rule.** Cards sit on surface tone with a hairline border.

**The 1.5px Rule.** Structural borders are 1.5px, not 1px. It is the one place the system
borrows syntax.fm's weight, and it is what keeps a flat card from dissolving into the ground.

## 5. Components

### Navigation
- **Topbar** — sticky, translucent ground, `backdrop-blur`. Brand mark (`Morning` in ink,
  `News` in sage), then pills, then the account on the right. On a phone it wraps so the
  brand and account share row one and the pills take row two.
- **Nav pill** (`.navpill`) — rounded-full, hairline border, mono bold. Active state is
  **solid sage with white text**, not a tinted background or an underline.
- **Settings rail** (`.rail-link`) — the same pill, stacked and sticky on desktop, a
  horizontally scrolling row on mobile. An `IntersectionObserver` moves the active state
  as the page scrolls.

### Episodes
- **Ghosted number** (`.ep-number`) — the signature. `clamp(5.5rem, 19vw, 10rem)` mono 800
  in sage-ghost, vertically centred, translated 12% past the right edge and clipped by the
  card. Hidden below `sm`, where a single narrow column has no room for it to sit behind.
- **Hero card** (`.card.ep`) — eyebrow, meta row, title, description, a `<dl>` of facts
  (weather / market / calendar / stories / messages / location), then an actions row
  separated by a hairline: play, **New episode**, show notes.
- **Episode row** (`.ep-row`) — play button, meta, title, description, and a smaller ghosted
  number. Border brightens to sage on hover.
- **Play button** (`.play-btn`) — a solid sage disc, the one place the accent fills a shape.
  Toggles its own play/pause glyph via `.is-playing`.

### Player
Fixed to the bottom, translucent surface, hairline top border. Toggle, truncated mono
title, a scrub range whose track is filled with a JS-driven `--played` gradient (native
range tracks do not fill), elapsed/total in mono, and a close button. `body.player-open`
adds bottom padding so nothing hides behind it. One `<audio>` element serves every play
button on the page, so starting one episode stops the last.

### Forms
- **Inputs** — `rounded-lg`, 1.5px border, sage focus ring at 3px.
- **Checkbox row** (`.checkbox-row`) — the whole labelled block is the target: checkbox,
  bold title, explanatory hint. Used for the segment toggles and the narrator rotation.
  Preferred over a bare inline checkbox wherever the setting needs a sentence of context.
- **Buttons** — rounded-full, mono bold. Primary is solid sage; `.btn-secondary` is a
  bordered surface pill; `.btn-ghost` is bare; `.btn-danger` is a bordered danger pill.
- **Settings group** (`.settings-group`) — a titled block. Consecutive groups are separated
  by a hairline, so every group must be a **direct sibling** of the others inside its
  section; put the `<form>` inside the group, not around it.
- **Unsaved-changes tracking** is opt-in via `[data-track-changes]` on the settings section
  container, so a login or a message box never warns on the way out.

### Feedback
Badges (`.badge-ready` / `-failed` / `-generating` / `-pending`), pill status chips in the
health list, `.tag` for optional/required/count annotations, `.flash` for inline banners,
and toasts for post-redirect confirmations.

## 6. Do's and Don'ts

### Do:
- **Do** use sage sparingly — primary CTA, active nav, focus ring, play disc, ready badge.
- **Do** give every content-bearing surface a 1.5px hairline and flat surface tone.
- **Do** cap measure on display text so it clears the ghosted number.
- **Do** respect `prefers-reduced-motion: reduce` — instant or crossfade only.
- **Do** design for a laptop at the breakfast table: generous tap targets, readable at
  arm's length.

### Don't:
- **Don't** set body copy in the display monospace, or a heading in the sans.
- **Don't** add a second chromatic accent. syntax.fm's amber is not part of this system.
- **Don't** use startup landing page clichés: hero metrics, gradient text, an eyebrow above
  every section, SaaS marketing scaffolding.
- **Don't** put a ghosted number on anything that is not an episode.
- **Don't** use side-stripe borders, gradient text, or glassmorphism as decoration — the
  `backdrop-blur` on the topbar and player is functional, not ornamental.
- **Don't** animate layout properties or gate content visibility on entrance animations.
