import { createContext, useContext } from 'react'
import type { AuthUser } from './api'

export interface AuthContextValue {
  user: AuthUser
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthGate')
  return value
}

/**
 * 是否管理员。缺少 AuthContext(如测试环境无 Provider)或 user 无 role 时
 * 一律按非管理员处理,返回 false。
 */
export function useIsAdmin(): boolean {
  const value = useContext(AuthContext)
  return value?.user?.role === 'admin'
}
