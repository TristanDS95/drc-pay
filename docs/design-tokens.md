# Design tokens — the look of the app

The single source of truth for the product's visual language, so the spec and any future client
code can't drift. Mirrors `../../drc-mvp-research/05-product-spec/ui-spec.md`: **Wave-style minimal**,
a distinctive **coral** accent, warm **cream + charcoal** neutrals, flat **12px-rounded** components
(no shadows), **Inter**. Light + dark (follows the system setting).

> Extracted from the former `apps/mobile/src/theme/tokens.ts` when `apps/` was removed (ADR 0008).
> When the mobile app is built, re-create `tokens.ts` from this note.

## Palette

| Token | Hex | Use |
|---|---|---|
| `coral` | `#FF6B5B` | primary accent / primary action |
| `coralDark` | `#E2553F` | pressed/hover accent |
| `cream` | `#FFFCF8` | light background |
| `charcoal` | `#1A1A1A` | dark background / primary text on light |
| `success` | `#1E8E5A` | semantic — success |
| `error` | `#D64541` | semantic — error |
| `warning` | `#C77700` | semantic — warning |

## Theme (semantic, light + dark)

| Role | Light | Dark |
|---|---|---|
| `background` | `#FFFCF8` (cream) | `#1A1A1A` (charcoal) |
| `surface` | `#FFFFFF` | `#242422` |
| `text` | `#1A1A1A` (charcoal) | `#F5F3EF` |
| `textMuted` | `#5A5A57` | `#A8A6A1` |
| `accent` | `#FF6B5B` (coral) | `#FF6B5B` (coral) |
| `border` | `#ECE8E1` | `#34332F` |

## Scale

- **Radius:** `sm 8` · `md 12` · `lg 16` · `pill 999`
- **Spacing:** `xs 4` · `sm 8` · `md 16` · `lg 24` · `xl 32`
- **Font:** family **Inter**; sizes `caption 13` · `body 16` · `title 22` · `display 32`
