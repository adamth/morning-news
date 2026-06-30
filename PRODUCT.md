# Product

## Register

product

## Users

A household of two — you and your partner — running a self-hosted morning news podcast on a home server (Unraid NAS). You use the web UI occasionally to configure sources, schedule, and voice; queue private messages that surprise the other person; and check that today's episode generated cleanly. Context is domestic and unhurried: kitchen-table setup, not power-user DevOps.

## Product Purpose

Morning News is a self-hosted service that gathers local news, weather, calendar events, and personal notes, then produces a short daily podcast episode delivered via RSS. The web UI exists to configure the show once, trust the daily pipeline, and manage the small set of interactions that matter: private messages, episode status, and the feed URL for podcast apps. Success looks like a reliable morning ritual with zero babysitting — configure it, listen, occasionally drop a note.

## Brand Personality

Warm, domestic, trustworthy. Like a kitchen radio: cozy without being cute, competent without being corporate. The interface should feel at home on a laptop at the breakfast table — honest, readable, unhurried. Voice is conversational and direct; no startup swagger, no enterprise density.

## Anti-references

- Startup landing page clichés: hero metrics, gradient text, eyebrow labels on every section, SaaS marketing scaffolding
- Generic dark dashboard monoculture when it reads as "another admin panel" rather than a household tool
- Consumer podcast app clones (Spotify/Apple Podcasts UI patterns) — this is configuration, not listening
- Over-designed empty states or onboarding theatrics that get in the way of setup

## Design Principles

1. **Kitchen-table utility** — Design for a household morning routine, not a SaaS operator. Surfaces should feel domestic and calm, not like managing infrastructure.
2. **Configure once, trust daily** — Setup flows (location, schedule, sources, voice) deserve clarity; daily use should be minimal. Status and episode health should be legible at a glance.
3. **Private surprises stay private** — The message privacy model is a product feature, not an implementation detail. Pending messages, ownership, and one-time read-aloud behavior should be obvious in the UI.
4. **Warmth through clarity** — Cozy doesn't mean decorative. Readable hierarchy, honest copy, and unhurried spacing carry the warmth; avoid ornament for its own sake.
5. **Show the state of your show** — Episode status, pending messages, feed URL, and generation errors should never require digging. The dashboard is a confidence check, not a control panel.

## Accessibility & Inclusion

Basics: readable body text with sufficient contrast, sensible focus states on form controls, and respect for `prefers-reduced-motion` when motion is added. No formal WCAG certification target; prioritize legibility for casual household use on varied screens and lighting.
