import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Outlet } from 'react-router-dom'
import { Loader2, RefreshCw, ShieldAlert } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type AuthUser } from '@/lib/api'
import { AuthContext } from '@/lib/auth'
import { setStorageUser } from '@/lib/storage'
import { resetAccountState as resetFinancialAiState } from '@/lib/aiReportStore'
import { resetAccountState as resetStockAiState } from '@/lib/stockAnalysisStore'
import { resetAccountState as resetBacktestState } from '@/lib/backtestTask'
import { resetAccountState as resetOptimizerState } from '@/lib/optimizerTask'
import { resetAccountState as resetWalkForwardState } from '@/lib/walkforwardTask'
import { resetAccountState as resetReviewState } from '@/lib/reviewStore'
import { resetAccountState as resetMonitorBadgeState } from '@/lib/monitorBadge'
import { resetAccountState as resetAskAiState } from '@/lib/askAiStore'
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
      setStorageUser(status.authenticated && status.user ? status.user.id : null)
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
      resetPrivateStores()
      queryClient.clear()
      setStorageUser(null)
      // Re-read the badge under the anonymous namespace after the scope flip.
      resetMonitorBadgeState()
      setUser(null)
    }
  }, [queryClient])

  const authenticate = useCallback((nextUser: AuthUser) => {
    // AccountEntry can be reached after a browser reload as well as after an
    // explicit switch. Clear before mounting the new account so prefetched
    // private queries and mutation callbacks cannot reuse shared keys.
    setStorageUser(nextUser.id)
    resetPrivateStores()
    queryClient.clear()
    setHasExistingAccounts(true)
    setUser(nextUser)
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
  if (!user) return <AccountEntry onAuthenticated={authenticate} hasExistingAccounts={hasExistingAccounts} />

  return (
    <AuthContext.Provider value={{ user, logout }}>
      {children ?? <Outlet />}
    </AuthContext.Provider>
  )
}

function resetPrivateStores(): void {
  resetFinancialAiState()
  resetStockAiState()
  resetBacktestState()
  resetOptimizerState()
  resetWalkForwardState()
  resetReviewState()
  resetMonitorBadgeState()
  resetAskAiState()
}
