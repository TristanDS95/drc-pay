/**
 * Design tokens — the single source of truth for the app's look.
 *
 * Mirrors drc-mvp-research/05-product-spec/ui-spec.md: Wave-style minimal, a
 * distinctive coral accent, warm cream + charcoal neutrals, flat 12px-rounded
 * components, Inter. Light + dark (follows the system setting).
 */

export const palette = {
  coral: '#FF6B5B', // primary accent / primary action
  coralDark: '#E2553F',
  cream: '#FFFCF8', // light background
  charcoal: '#1A1A1A', // dark background / primary text on light
  // semantic
  success: '#1E8E5A',
  error: '#D64541',
  warning: '#C77700',
} as const;

export const theme = {
  light: {
    background: palette.cream,
    surface: '#FFFFFF',
    text: palette.charcoal,
    textMuted: '#5A5A57',
    accent: palette.coral,
    border: '#ECE8E1',
  },
  dark: {
    background: palette.charcoal,
    surface: '#242422',
    text: '#F5F3EF',
    textMuted: '#A8A6A1',
    accent: palette.coral,
    border: '#34332F',
  },
} as const;

export const radius = { sm: 8, md: 12, lg: 16, pill: 999 } as const;
export const spacing = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 } as const;
export const font = {
  family: 'Inter',
  sizes: { caption: 13, body: 16, title: 22, display: 32 },
} as const;
