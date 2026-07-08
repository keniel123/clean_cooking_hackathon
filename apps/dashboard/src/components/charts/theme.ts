/**
 * Chart color constants. SVG presentation attributes can't resolve CSS
 * variables, so the validated palette hexes are mirrored here from
 * `src/index.css` — keep the two in sync.
 */
export const SERIES = {
  solar: '#eda100',
  battery: '#1baf7a',
  load: '#4a3aa7',
  revenue: '#2a78d6',
} as const

export const CHART_INK = {
  ink: '#0b0b0b',
  secondary: '#52514e',
  muted: '#898781',
  grid: '#e1e0d9',
  baseline: '#c3c2b7',
  critical: '#d03b3b',
} as const

export const AXIS_TICK = { fontSize: 11, fill: CHART_INK.muted } as const

/** Compact axis numbers: 1200 -> "1.2K". */
export function compactNumber(n: number): string {
  return Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}
