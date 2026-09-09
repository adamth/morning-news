# Morning News

Self-hosted daily news podcast generator. See [README.md](README.md) for setup.

## Design Context

Strategic and visual design context lives in:

- **[PRODUCT.md](PRODUCT.md)** — register (`product`), household users, warm-domestic personality, anti-references, design principles
- **[DESIGN.md](DESIGN.md)** — the implemented visual system ("The Kitchen Radio": restrained sage accent on a light ground, monospace display + sans body, flat 1.5px-hairline surfaces, syntax.fm's pill nav / ghosted episode numbers / sticky player). Tokens live in [assets/input.css](assets/input.css); `npm run build:css` compiles them.

Impeccable live mode is configured at `.impeccable/live/config.json` (Jinja templates, port 8080 dev server).
