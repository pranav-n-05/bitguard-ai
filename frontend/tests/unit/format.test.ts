import { describe, expect, it } from 'vitest'
import { formatDate, formatNumber, formatSat, satToBtc, shortHash, UNAVAILABLE } from '@/utils/format'

describe('satToBtc', () => {
  it('uses exact integer arithmetic', () => {
    expect(satToBtc(1)).toBe('0.00000001 BTC')
    expect(satToBtc(100_000_000)).toBe('1 BTC')
    expect(satToBtc(2_100_000_000_000_000)).toBe('21,000,000 BTC')
    expect(satToBtc(30_000_000)).toBe('0.3 BTC')
  })
  it('never renders missing values as zero', () => {
    expect(satToBtc(null)).toBe(UNAVAILABLE)
    expect(satToBtc(undefined)).toBe(UNAVAILABLE)
    expect(formatSat(null)).toBe(UNAVAILABLE)
    expect(formatNumber(undefined)).toBe(UNAVAILABLE)
    expect(formatDate(null)).toBe(UNAVAILABLE)
    expect(formatDate('garbage')).toBe(UNAVAILABLE)
  })
})

describe('misc formatting', () => {
  it('formats UTC dates and short hashes', () => {
    expect(formatDate('2026-01-02T03:04:05+05:30')).toBe('2026-01-01 21:34:05 UTC')
    expect(shortHash('a'.repeat(64))).toBe(`${'a'.repeat(10)}…${'a'.repeat(6)}`)
    expect(formatSat(0)).toBe('0 sat')
  })
})
