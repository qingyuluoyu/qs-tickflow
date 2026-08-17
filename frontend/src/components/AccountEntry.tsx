import { useState, type FormEvent } from 'react'
import { Loader2, ShieldAlert, UserRound, Eye, EyeOff } from 'lucide-react'
import { motion } from 'framer-motion'
import { api, type AuthUser } from '@/lib/api'
import { cn } from '@/lib/cn'

interface AccountEntryProps {
  onAuthenticated: (user: AuthUser) => void
}

/** Site entry card: creates a new local account or enters an existing one. */
export function AccountEntry({ onAuthenticated }: AccountEntryProps) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!name || !phone || !password) {
      setError('请填写姓名、电话和密码')
      return
    }
    setError('')
    setPending(true)
    try {
      const result = await api.authEntry(name, phone, password)
      onAuthenticated(result.user)
    } catch (cause: any) {
      setError(cause?.message || '进入失败，请稍后重试')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-base px-4">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(59,130,246,0.14),transparent_42%),radial-gradient(circle_at_70%_80%,rgba(20,184,166,0.12),transparent_42%)]" />
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
        className="relative w-full max-w-sm"
      >
        <div className="mb-6 flex justify-center">
          <img src="/brand-wordmark.png" alt="清数智算 · 智能投研工作台" className="h-auto w-64 object-contain" />
        </div>
        <div className="rounded-card border border-border bg-surface/95 p-6 shadow-2xl backdrop-blur">
          <div className="mb-5 flex items-center gap-2.5">
            <div className="grid h-9 w-9 place-items-center rounded-lg bg-accent/15 text-accent">
              <UserRound className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-medium text-foreground">进入投研工作台</div>
              <div className="text-[11px] text-muted">首次填写会创建个人空间，之后使用电话和密码进入</div>
            </div>
          </div>
          <form onSubmit={submit} autoComplete="off" className="space-y-3">
            <input
              value={name}
              onChange={event => setName(event.target.value)}
              placeholder="姓名"
              autoComplete="off"
              autoFocus
              className="h-10 w-full rounded-btn border border-border bg-base px-3 text-sm text-foreground outline-none transition-colors focus:border-accent/50"
            />
            <input
              value={phone}
              onChange={event => setPhone(event.target.value)}
              placeholder="电话"
              autoComplete="off"
              className="h-10 w-full rounded-btn border border-border bg-base px-3 text-sm text-foreground outline-none transition-colors focus:border-accent/50"
            />
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={event => setPassword(event.target.value)}
                placeholder="密码"
                autoComplete="new-password"
                className="h-10 w-full rounded-btn border border-border bg-base px-3 pr-9 text-sm text-foreground outline-none transition-colors focus:border-accent/50"
              />
              <button
                type="button"
                onClick={() => setShowPassword(value => !value)}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted hover:text-foreground"
                tabIndex={-1}
                aria-label={showPassword ? '隐藏密码' : '显示密码'}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            {error && (
              <div className="flex items-start gap-1.5 rounded-btn bg-danger/10 px-3 py-2 text-[11px] text-danger">
                <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            <button
              type="submit"
              disabled={pending || !name || !phone || !password}
              className={cn(
                'inline-flex h-10 w-full items-center justify-center gap-1.5 rounded-btn bg-accent text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50',
              )}
            >
              {pending ? <><Loader2 className="h-4 w-4 animate-spin" />正在进入…</> : '进入工作台'}
            </button>
          </form>
          <p className="mt-3 text-[10px] leading-relaxed text-muted/70">
            姓名、电话和密码按原样保存（密码仅保存不可逆哈希），每个账户的个人数据相互隔离。
          </p>
        </div>
      </motion.div>
    </div>
  )
}
