import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'
import { problemMessage, tokens } from '@/services/api'

describe('api helpers', () => {
  it('extracts RFC 9457 problem details', () => {
    const err = new AxiosError('x', '422', undefined, undefined, {
      status: 422, statusText: '', headers: {}, config: { headers: new AxiosHeaders() },
      data: { title: 'Validation', status: 422, detail: 'Request validation failed', errors: [{ loc: ['body', 'title'], msg: 'too short' }] },
    })
    expect(problemMessage(err)).toBe('title: too short')
  })
  it('reports unreachable API', () => {
    expect(problemMessage(new AxiosError('Network Error', 'ERR_NETWORK'))).toMatch(/unreachable/)
  })
  it('keeps access token in memory and refresh token in session storage', () => {
    tokens.set({ access_token: 'a', refresh_token: 'r', expires_at: '' })
    expect(tokens.access).toBe('a')
    expect(sessionStorage.getItem('bitguard.refresh')).toBe('r')
    expect(localStorage.length).toBe(0)
    tokens.clear()
    expect(tokens.access).toBeNull()
    expect(sessionStorage.getItem('bitguard.refresh')).toBeNull()
  })
})
