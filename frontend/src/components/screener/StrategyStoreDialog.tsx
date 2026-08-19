import { useCallback, useEffect, useMemo, useState } from 'react'
import { Modal as MantineModal } from '@mantine/core'
import { AlertTriangle, Loader2, RotateCcw, ShieldCheck, Trash2, X } from 'lucide-react'
import { api, type StrategyDetail } from '@/lib/api'

interface Props {
  open: boolean
  onClose: () => void
  onDeleted?: (strategyId: string) => void
  onRestored?: (builtinStrategyIds: string[]) => void
}

const SOURCE_LABEL: Record<string, string> = {
  builtin: '内置',
  custom: '自定义',
  ai: 'AI',
  composite: '叠加',
}

const SOURCE_CLS: Record<string, string> = {
  builtin: 'bg-accent/10 text-accent border-accent/20',
  custom: 'bg-amber-400/10 text-amber-400 border-amber-400/30',
  ai: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  composite: 'bg-teal-400/10 text-teal-400 border-teal-400/30',
}

/** 策略管理: 查看策略来源、删除用户策略、恢复打包的 18 个内置策略。 */
export function StrategyManagementDialog({ open, onClose, onDeleted, onRestored }: Props) {
  const [strategies, setStrategies] = useState<StrategyDetail[]>([])
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const loadStrategies = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await api.strategyList()
      setStrategies(result.strategies)
    } catch (e: any) {
      setError(String(e?.message ?? '策略列表加载失败'))
      setStrategies([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void loadStrategies()
  }, [open, loadStrategies])

  const builtinCount = useMemo(() => strategies.filter(s => s.source === 'builtin').length, [strategies])
  const userStrategies = useMemo(
    () => strategies.filter(s => s.source !== 'builtin'),
    [strategies],
  )

  const handleDelete = async (strategy: StrategyDetail) => {
    if (strategy.source === 'builtin' || busyId || restoring) return
    const confirmed = window.confirm(
      `确定删除「${strategy.name || strategy.id}」吗？\n\n策略源文件、配置和关联监控将被清除，且无法恢复。`,
    )
    if (!confirmed) return

    setBusyId(strategy.id)
    setError('')
    setMessage('')
    try {
      await api.strategyDelete(strategy.id)
      onDeleted?.(strategy.id)
      setMessage(`已删除策略「${strategy.name || strategy.id}」`)
      await loadStrategies()
    } catch (e: any) {
      setError(String(e?.message ?? '删除失败，请先解除叠加策略引用后重试'))
    } finally {
      setBusyId(null)
    }
  }

  const handleRestore = async () => {
    if (restoring || busyId) return
    const confirmed = window.confirm(
      '回退初始版本将删除当前用户的自定义、AI 和叠加策略，并清除策略参数覆盖，恢复为 18 个内置策略。\n\n自选股、账户和行情数据不会受影响。确定继续吗？',
    )
    if (!confirmed) return

    setRestoring(true)
    setError('')
    setMessage('')
    try {
      const result = await api.strategyRestoreDefaults()
      onRestored?.(result.builtin_strategy_ids)
      setMessage(`已恢复初始版本，共 ${result.count} 个内置策略`)
      await loadStrategies()
    } catch (e: any) {
      setError(String(e?.message ?? '恢复失败，请检查策略目录是否可写'))
    } finally {
      setRestoring(false)
    }
  }

  return (
    <MantineModal
      opened={open}
      onClose={onClose}
      withCloseButton={false}
      centered
      padding={0}
      transitionProps={{ duration: 150 }}
      overlayProps={{ backgroundOpacity: 0.5 }}
      classNames={{
        content: 'w-[680px] max-h-[78vh] bg-surface border border-border rounded-card shadow-xl flex flex-col',
        body: 'flex min-h-0 flex-1 flex-col',
      }}
      styles={{ content: { flex: '0 1 auto' } }}
    >
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-border shrink-0">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-accent" />
                <span className="text-sm font-medium text-foreground">管理策略</span>
                <span className="text-[11px] text-muted">{builtinCount} 个内置 · {userStrategies.length} 个自建</span>
              </div>
              <button onClick={onClose} aria-label="关闭" className="p-1 rounded hover:bg-elevated transition-colors cursor-pointer">
                <X className="h-4 w-4 text-muted" />
              </button>
            </div>

            <div className="px-4 py-2 border-b border-border/60 text-[11px] leading-4 text-muted flex items-start gap-2">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5" />
              <span>内置策略由平台维护不可删除；自定义、AI 和叠加策略只属于当前账户。</span>
            </div>

            {(error || message) && (
              <div className={`mx-4 mt-2 px-3 py-2 rounded-btn border text-[11px] shrink-0 ${error ? 'border-danger/20 bg-danger/10 text-danger' : 'border-emerald-400/20 bg-emerald-400/10 text-emerald-400'}`}>
                {error || message}
              </div>
            )}

            <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2">
              {loading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-5 w-5 animate-spin text-accent" />
                </div>
              ) : strategies.length === 0 ? (
                <div className="flex items-center justify-center py-16 text-xs text-muted">暂无策略</div>
              ) : (
                <div className="space-y-1">
                  {strategies.map(strategy => {
                    const isBuiltin = strategy.source === 'builtin'
                    const deleting = busyId === strategy.id
                    return (
                      <div key={strategy.id} className="flex items-center gap-3 px-3 py-2 rounded-btn border border-border/50 bg-base/40 hover:bg-elevated/60 transition-colors">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-xs font-medium text-foreground truncate">{strategy.name || strategy.id}</span>
                            <span className={`text-[9px] px-1.5 py-0.5 rounded border shrink-0 ${SOURCE_CLS[strategy.source] ?? SOURCE_CLS.custom}`}>
                              {SOURCE_LABEL[strategy.source] ?? strategy.source}
                            </span>
                          </div>
                          <div className="text-[10px] text-muted font-mono truncate mt-0.5">{strategy.id}</div>
                        </div>
                        {isBuiltin ? (
                          <span className="text-[10px] text-muted shrink-0">平台策略</span>
                        ) : (
                          <button
                            onClick={() => void handleDelete(strategy)}
                            disabled={!!busyId || restoring}
                            aria-label={`删除策略 ${strategy.name || strategy.id}`}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded border border-danger/25 text-[10px] text-danger hover:bg-danger/10 disabled:opacity-40 transition-colors cursor-pointer shrink-0"
                          >
                            {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                            删除
                          </button>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between px-4 py-2.5 border-t border-border shrink-0">
              <button
                onClick={() => void handleRestore()}
                disabled={restoring || !!busyId || loading}
                className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-btn border border-amber-400/30 bg-amber-400/8 text-[11px] text-amber-400 hover:bg-amber-400/15 disabled:opacity-50 transition-colors cursor-pointer"
              >
                {restoring ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
                {restoring ? '恢复中…' : '回退初始版本'}
              </button>
              <button
                onClick={onClose}
                className="h-7 px-3 rounded-btn border border-border text-xs text-secondary hover:text-foreground transition-colors cursor-pointer"
              >
                关闭
              </button>
            </div>
    </MantineModal>
  )
}

// 兼容历史调用方，避免外部页面在升级时失效。
export const StrategyStoreDialog = StrategyManagementDialog
