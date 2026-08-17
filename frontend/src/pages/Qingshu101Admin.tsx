import { useEffect, useState } from 'react'
import { KeyRound, Loader2, LogOut, RefreshCw, ShieldCheck } from 'lucide-react'
import { api, type Qingshu101DirectoryStatus, type Qingshu101User } from '@/lib/api'

const PAGE_SIZE = 100

function formatTime(value: number) {
  if (!value) return '—'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

/** Hidden operator page; it is not linked from the customer navigation. */
export function Qingshu101Admin() {
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [authenticated, setAuthenticated] = useState(false)
  const [key, setKey] = useState('')
  const [users, setUsers] = useState<Qingshu101User[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [refreshedAt, setRefreshedAt] = useState(0)
  const [directoryStatus, setDirectoryStatus] = useState<Qingshu101DirectoryStatus | null>(null)
  const [pending, setPending] = useState(true)
  const [error, setError] = useState('')

  const loadUsers = async (nextOffset = offset) => {
    setPending(true)
    setError('')
    try {
      const result = await api.qingshu101Users(nextOffset, PAGE_SIZE)
      setUsers(result.users)
      setTotal(result.total)
      setOffset(result.offset)
      setRefreshedAt(result.refreshed_at)
      setDirectoryStatus(result.directory_status)
    } catch (cause: any) {
      setError(cause?.message || '注册目录加载失败')
    } finally {
      setPending(false)
    }
  }

  useEffect(() => {
    let active = true
    api.qingshu101Status()
      .then(result => {
        if (!active) return
        setConfigured(result.configured)
        setAuthenticated(result.authenticated)
        setDirectoryStatus(result.directory)
        if (result.authenticated) void loadUsers(0)
        else setPending(false)
      })
      .catch(cause => {
        if (!active) return
        setError(cause?.message || '管理入口不可用')
        setPending(false)
      })
    return () => { active = false }
    // Initial status check only. loadUsers is stable for this page lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!authenticated) return
    const timer = window.setInterval(() => { void loadUsers(offset) }, 30_000)
    return () => window.clearInterval(timer)
    // The current page and offset are the only inputs for the server refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated, offset])

  const login = async () => {
    if (!key) return
    setPending(true)
    setError('')
    try {
      await api.qingshu101CreateSession(key)
      setAuthenticated(true)
      setKey('')
      await loadUsers(0)
    } catch (cause: any) {
      setError(cause?.message || '管理员密钥错误')
      setPending(false)
    }
  }

  const logout = async () => {
    await api.qingshu101Logout().catch(() => undefined)
    setAuthenticated(false)
    setUsers([])
    setTotal(0)
    setDirectoryStatus(null)
  }

  if (configured === null) {
    return <div className="grid min-h-screen place-items-center bg-base text-muted"><Loader2 className="h-5 w-5 animate-spin" /></div>
  }

  return (
    <div className="min-h-screen bg-base px-5 py-8 text-foreground sm:px-10">
      <div className="mx-auto max-w-6xl">
        <div className="mb-8 flex items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-muted">
              <ShieldCheck className="h-4 w-4 text-accent" /> QINGSHU101 OPERATOR
            </div>
            <h1 className="text-2xl font-semibold">注册目录</h1>
            <p className="mt-2 text-sm text-muted">服务端预处理的账户元数据。密码及密码哈希永不展示。</p>
          </div>
          {authenticated && (
            <button type="button" onClick={logout} className="inline-flex items-center gap-2 rounded-btn border border-border px-3 py-2 text-sm text-secondary hover:bg-elevated">
              <LogOut className="h-4 w-4" />退出管理
            </button>
          )}
        </div>

        {!configured ? (
          <div className="rounded-card border border-warning/30 bg-warning/10 p-5 text-sm text-secondary">
            qingshu101 管理入口尚未启用。请在服务器环境变量设置 <code className="rounded bg-elevated px-1.5 py-0.5">QINGSHU101_ADMIN_KEY</code> 后重启服务。
          </div>
        ) : !authenticated ? (
          <div className="max-w-md rounded-card border border-border bg-surface p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium"><KeyRound className="h-4 w-4 text-accent" />管理员密钥</div>
            <input
              type="password"
              value={key}
              onChange={event => setKey(event.target.value)}
              onKeyDown={event => { if (event.key === 'Enter') void login() }}
              placeholder="输入服务器环境变量中的密钥"
              className="h-10 w-full rounded-btn border border-border bg-base px-3 text-sm outline-none focus:border-accent/60"
            />
            {error && <div className="mt-3 rounded-btn bg-danger/10 px-3 py-2 text-xs text-danger">{error}</div>}
            <button type="button" onClick={login} disabled={!key || pending} className="mt-4 inline-flex h-10 w-full items-center justify-center gap-2 rounded-btn bg-accent px-4 text-sm font-medium text-white disabled:opacity-50">
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}进入注册目录
            </button>
          </div>
        ) : (
          <>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface px-4 py-3 text-sm">
              <div>共 <span className="font-semibold tabular-nums">{total}</span> 个注册账户</div>
              <div className="flex items-center gap-3 text-xs text-muted">
                <span className={directoryStatus?.stale ? 'text-warning' : 'text-muted'}>
                  {directoryStatus?.stale ? '目录陈旧' : '目录正常'} · 预处理：{formatTime(refreshedAt)}
                  {directoryStatus?.last_error ? ` · ${directoryStatus.last_error}` : ''}
                </span>
                <button type="button" onClick={() => void loadUsers(offset)} className="inline-flex items-center gap-1 rounded px-2 py-1 hover:bg-elevated" title="刷新目录"><RefreshCw className="h-3.5 w-3.5" />刷新</button>
              </div>
            </div>
            {error && <div className="mb-4 rounded-btn bg-danger/10 px-3 py-2 text-xs text-danger">{error}</div>}
            <div className="overflow-x-auto rounded-card border border-border bg-surface">
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead className="border-b border-border bg-elevated/60 text-xs text-muted">
                  <tr><th className="px-4 py-3">序号</th><th className="px-4 py-3">姓名</th><th className="px-4 py-3">电话</th><th className="px-4 py-3">创建时间</th><th className="px-4 py-3">最近更新</th></tr>
                </thead>
                <tbody>
                  {users.map((user, index) => (
                    <tr key={user.id} className="border-b border-border/70 last:border-0">
                      <td className="px-4 py-3 tabular-nums text-muted">{offset + index + 1}</td>
                      <td className="px-4 py-3 font-medium">{user.name}</td>
                      <td className="px-4 py-3 tabular-nums">{user.phone}</td>
                      <td className="px-4 py-3 text-secondary">{formatTime(user.created_at)}</td>
                      <td className="px-4 py-3 text-secondary">{formatTime(user.updated_at)}</td>
                    </tr>
                  ))}
                  {!users.length && <tr><td colSpan={5} className="px-4 py-12 text-center text-muted">暂无账户</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2 text-sm">
              <button type="button" disabled={offset === 0 || pending} onClick={() => void loadUsers(Math.max(0, offset - PAGE_SIZE))} className="rounded-btn border border-border px-3 py-1.5 disabled:opacity-40">上一页</button>
              <span className="text-xs text-muted">{total ? `${offset + 1}-${Math.min(offset + users.length, total)} / ${total}` : '0 / 0'}</span>
              <button type="button" disabled={offset + users.length >= total || pending} onClick={() => void loadUsers(offset + PAGE_SIZE)} className="rounded-btn border border-border px-3 py-1.5 disabled:opacity-40">下一页</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
