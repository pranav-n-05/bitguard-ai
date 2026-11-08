import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, refreshAccess, tokens } from '@/services/api'
import type { TokenPair, User } from '@/types/api'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string, otp?: string) => Promise<void>
  logout: () => Promise<void>
  can: (perm: string) => boolean
  reload: () => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const qc = useQueryClient()

  const loadMe = useCallback(async () => {
    try {
      setUser((await api.get<User>('/auth/me')).data)
    } catch {
      setUser(null)
    }
  }, [])

  useEffect(() => {
    let alive = true
    ;(async () => {
      if (tokens.refresh && (await refreshAccess())) await loadMe()
      if (alive) setLoading(false)
    })()
    const off = tokens.subscribe((authed) => {
      if (!authed) setUser(null)
    })
    return () => {
      alive = false
      off()
    }
  }, [loadMe])

  const login = useCallback(
    async (email: string, password: string, otp?: string) => {
      const r = await api.post<TokenPair>('/auth/login', { email, password, ...(otp ? { otp } : {}) })
      tokens.set(r.data)
      await loadMe()
    },
    [loadMe],
  )

  const logout = useCallback(async () => {
    const rt = tokens.refresh
    try {
      if (rt) await api.post('/auth/logout', { refresh_token: rt })
    } finally {
      tokens.clear()
      qc.clear()
    }
  }, [qc])

  const value = useMemo<AuthState>(
    () => ({ user, loading, login, logout, reload: loadMe, can: (p) => !!user?.permission_codes.includes(p) }),
    [user, loading, login, logout, loadMe],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth must be used inside AuthProvider')
  return v
}
