import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Outlet } from 'react-router-dom'
import { Loader2, RefreshCw, ShieldAlert } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type AuthUser } from '@/lib/api'
import { AuthContext } from '@/lib/auth'
import { AccountEntry } from './AccountEntry'

export function AuthGate({ children }: { children?: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<AuthUser | null>(null)
  const [hasExistingAccounts, setHasExistingAccounts] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const loadStatus = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const status = await api.authStatus()
      setHasExistingAccounts(status.configured)
      setUser(status.authenticated ? status.user : null)
    } catch (cause: any) {
      setLoadError(cause?.message || '无法连接服务')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadStatus() }, [loadStatus])

  const logout = useCallback(async () => {
    try {
      // Stop old-account requests before switching identity. Otherwise a
      // response that completes after logout could repopulate shared query
      // keys with the previous account's private data.
      await queryClient.cancelQueries()
      await api.authLogout()
    } finally {
      // Do not retain one account's private query cache when another account
      // enters in the same browser tab.
      queryClient.clear()
      setUser(null)
    }
  }, [queryClient])

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center bg-base"><Loader2 className="h-6 w-6 animate-spin text-muted" /></div>
  }
  if (loadError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base px-4">
        <div className="max-w-sm rounded-card border border-border bg-surface p-6 text-center">
          <ShieldAlert className="mx-auto h-8 w-8 text-danger" />
          <p className="mt-3 text-sm text-foreground">{loadError}</p>
          <button onClick={() => void loadStatus()} className="mt-4 inline-flex items-center gap-1.5 rounded-btn bg-accent px-4 py-2 text-sm text-white">
            <RefreshCw className="h-4 w-4" />重试
          </button>
        </div>
      </div>
    )
  }
  if (!user) return <AccountEntry onAuthenticated={setUser} hasExistingAccounts={hasExistingAccounts} />

  return (
    <AuthContext.Provider value={{ user, logout }}>
      {children ?? <Outlet />}
    </AuthContext.Provider>
  )
}
