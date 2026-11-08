import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** URL-backed filter state so views are shareable and survive reloads. */
export function useSearchState() {
  const [params, setParams] = useSearchParams()
  const get = useCallback((k: string) => params.get(k), [params])
  const set = useCallback(
    (updates: Record<string, string | number | null | undefined>, resetOffset = true) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(updates)) {
          if (v === null || v === undefined || v === '') next.delete(k)
          else next.set(k, String(v))
        }
        if (resetOffset && !('offset' in updates)) next.delete('offset')
        return next
      })
    },
    [setParams],
  )
  return { params, get, set }
}
