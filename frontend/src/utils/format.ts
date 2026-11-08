/** Formatting helpers. Missing values are rendered explicitly — never as zero. */

export const UNAVAILABLE = '—'

/** Satoshis are integers end-to-end; BTC strings are produced by integer arithmetic (no float rounding). */
export function satToBtc(sat: number | null | undefined): string {
  if (sat === null || sat === undefined || !Number.isFinite(sat)) return UNAVAILABLE
  const neg = sat < 0
  const abs = BigInt(Math.abs(Math.trunc(sat)))
  const whole = abs / 100000000n
  const frac = (abs % 100000000n).toString().padStart(8, '0').replace(/0+$/, '')
  return `${neg ? '-' : ''}${whole.toLocaleString('en-US')}${frac ? '.' + frac : ''} BTC`
}

export function formatSat(sat: number | null | undefined): string {
  if (sat === null || sat === undefined) return UNAVAILABLE
  return `${sat.toLocaleString('en-US')} sat`
}

export function formatNumber(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return UNAVAILABLE
  return n.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 })
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return UNAVAILABLE
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return UNAVAILABLE
  return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC'
}

export function shortHash(h: string | null | undefined, n = 10): string {
  if (!h) return UNAVAILABLE
  return h.length <= n * 2 + 1 ? h : `${h.slice(0, n)}…${h.slice(-6)}`
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return UNAVAILABLE
  return `${(v * 100).toFixed(digits)}%`
}

export function titleCase(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
