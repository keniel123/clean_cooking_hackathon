/**
 * Locale-aware formatting built on Intl. The active locale is set by
 * I18nProvider via `setFormatLocale`; components re-render on language
 * change (they consume the i18n context), so formatted output follows.
 */

export type FormatLang = 'en' | 'sw'

let locale = 'en-KE'

export function setFormatLocale(lang: FormatLang): void {
  locale = lang === 'sw' ? 'sw-KE' : 'en-KE'
}

const numberFormats = new Map<string, Intl.NumberFormat>()
const dateFormats = new Map<string, Intl.DateTimeFormat>()
const relativeFormats = new Map<string, Intl.RelativeTimeFormat>()

function nf(options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = locale + JSON.stringify(options)
  let fmt = numberFormats.get(key)
  if (!fmt) {
    fmt = new Intl.NumberFormat(locale, options)
    numberFormats.set(key, fmt)
  }
  return fmt
}

function df(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = locale + JSON.stringify(options)
  let fmt = dateFormats.get(key)
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(locale, options)
    dateFormats.set(key, fmt)
  }
  return fmt
}

// ------------------------------------------------------------------ numbers

export function formatKes(amount: number): string {
  return nf({ style: 'currency', currency: 'KES', maximumFractionDigits: 0 }).format(amount)
}

export function formatKesCompact(amount: number): string {
  if (amount < 100_000) return formatKes(amount)
  return nf({
    style: 'currency',
    currency: 'KES',
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(amount)
}

export function formatNumber(n: number): string {
  return nf({}).format(n)
}

export function formatKw(kw: number): string {
  return `${nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(kw)} kW`
}

export function formatKwh(kwh: number): string {
  const f = nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 })
  return kwh >= 1000 ? `${f.format(kwh / 1000)} MWh` : `${f.format(kwh)} kWh`
}

export function formatPct(pct: number): string {
  return `${Math.round(pct)}%`
}

// -------------------------------------------------------------------- dates

export function formatDate(iso: string): string {
  return df({ day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso))
}

export function formatDateTime(iso: string): string {
  return df({
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(iso))
}

/** Chart tick: "14:00" */
export function formatHourMinute(iso: string): string {
  return df({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(iso))
}

/** Chart tick: "Mon 5" / "Jumatatu 5" (short weekday + day of month) */
export function formatWeekdayDay(iso: string): string {
  return df({ weekday: 'short', day: 'numeric' }).format(new Date(iso))
}

/** Chart tick: "5 Jul" */
export function formatDayMonth(iso: string): string {
  return df({ day: 'numeric', month: 'short' }).format(new Date(iso))
}

const RELATIVE_STEPS: { limit: number; divisor: number; unit: Intl.RelativeTimeFormatUnit }[] = [
  { limit: 60, divisor: 1, unit: 'second' },
  { limit: 3600, divisor: 60, unit: 'minute' },
  { limit: 86400, divisor: 3600, unit: 'hour' },
  { limit: 86400 * 30, divisor: 86400, unit: 'day' },
  { limit: 86400 * 365, divisor: 86400 * 30, unit: 'month' },
  { limit: Infinity, divisor: 86400 * 365, unit: 'year' },
]

/** "3 days ago" / "siku 3 zilizopita" */
export function timeAgo(iso: string): string {
  let fmt = relativeFormats.get(locale)
  if (!fmt) {
    fmt = new Intl.RelativeTimeFormat(locale, { numeric: 'always' })
    relativeFormats.set(locale, fmt)
  }
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  const step = RELATIVE_STEPS.find((s) => Math.abs(seconds) < s.limit)!
  return fmt.format(-Math.round(seconds / step.divisor), step.unit)
}
