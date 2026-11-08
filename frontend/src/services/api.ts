import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import type { Problem, TokenPair } from '@/types/api'

/**
 * Token handling: the short-lived access token lives only in memory. The refresh token is kept in
 * sessionStorage (cleared when the tab closes) and rotated on every refresh; reuse is detected server-side.
 */
const REFRESH_KEY = 'bitguard.refresh'
let accessToken: string | null = null
let refreshing: Promise<string | null> | null = null
const listeners = new Set<(authed: boolean) => void>()

export const tokens = {
  set(pair: TokenPair) {
    accessToken = pair.access_token
    sessionStorage.setItem(REFRESH_KEY, pair.refresh_token)
    listeners.forEach((l) => l(true))
  },
  clear() {
    accessToken = null
    sessionStorage.removeItem(REFRESH_KEY)
    listeners.forEach((l) => l(false))
  },
  get access() {
    return accessToken
  },
  get refresh() {
    return sessionStorage.getItem(REFRESH_KEY)
  },
  subscribe(fn: (authed: boolean) => void) {
    listeners.add(fn)
    return () => listeners.delete(fn)
  },
}

export const api = axios.create({ baseURL: '/api/v1', timeout: 120_000 })

api.interceptors.request.use((cfg) => {
  if (accessToken) cfg.headers.Authorization = `Bearer ${accessToken}`
  cfg.headers['X-Request-ID'] = crypto.randomUUID().replace(/-/g, '')
  return cfg
})

export async function refreshAccess(): Promise<string | null> {
  const rt = tokens.refresh
  if (!rt) return null
  refreshing ??= axios
    .post<TokenPair>('/api/v1/auth/refresh', { refresh_token: rt })
    .then((r) => {
      tokens.set(r.data)
      return r.data.access_token
    })
    .catch(() => {
      tokens.clear()
      return null
    })
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

api.interceptors.response.use(undefined, async (error: AxiosError) => {
  const cfg = error.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined
  if (error.response?.status === 401 && cfg && !cfg._retried && !cfg.url?.includes('/auth/')) {
    cfg._retried = true
    const t = await refreshAccess()
    if (t) return api(cfg)
  }
  return Promise.reject(error)
})

export function problemMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const p = err.response?.data as Problem | undefined
    if (p?.errors?.length) return p.errors.map((e) => `${e.loc.slice(1).join('.')}: ${e.msg}`).join('; ')
    if (p?.detail) return p.detail
    if (err.code === 'ECONNABORTED') return 'The request timed out.'
    if (!err.response) return 'The API is unreachable. Check that the backend is running.'
    return `Request failed (${err.response.status}).`
  }
  return err instanceof Error ? err.message : 'Unexpected error'
}

export function httpStatus(err: unknown): number | undefined {
  return axios.isAxiosError(err) ? err.response?.status : undefined
}

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return (await api.get<T>(url, { params, paramsSerializer: { indexes: null } })).data
}
export async function post<T>(url: string, body?: unknown): Promise<T> {
  return (await api.post<T>(url, body)).data
}
export async function patch<T>(url: string, body?: unknown): Promise<T> {
  return (await api.patch<T>(url, body)).data
}

export async function download(url: string, fallbackName: string): Promise<{ sha256: string | null }> {
  const r = await api.get<Blob>(url, { responseType: 'blob' })
  const disp = (r.headers['content-disposition'] as string | undefined) ?? ''
  const name = /filename="([^"]+)"/.exec(disp)?.[1] ?? fallbackName
  const href = URL.createObjectURL(r.data)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.click()
  URL.revokeObjectURL(href)
  return { sha256: (r.headers['x-content-sha256'] as string | undefined) ?? null }
}
