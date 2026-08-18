import { useEffect, useRef, useState, useCallback } from 'react'
import { ActionIcon, Modal as MantineModal, Tooltip } from '@mantine/core'
import {
  X, Sparkles, Loader2, AlertTriangle, Copy, Check, RefreshCw,
  Settings2, Send, Wand2, Minimize2, Maximize2, History, LineChart, ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { copyText } from '@/lib/clipboard'
import { toast } from '@/lib/notify'
import { MarkdownRenderer } from '@/components/financials/MarkdownRenderer'
import {
  type ActiveTask, type HistoryReport,
  minimizeDialog, closeDialog, startAnalysis,
} from '@/lib/stockAnalysisStore'

/**
 * AI 个股分析对话框 —— 蓝色主题,与财务分析对话框区分。
 * 复用 MarkdownRenderer(通用 markdown 渲染);标题/配色/文案独立。
 */

interface Props {
  task: ActiveTask | HistoryReport | null
  mode: 'active' | 'history' | null
  minimized: boolean
}

type Phase = 'loading' | 'streaming' | 'done' | 'error'

function getPhase(task: ActiveTask | HistoryReport | null): Phase {
  if (!task) return 'loading'
  if ('phase' in task) return task.phase
  return 'done'
}
function getContent(task: ActiveTask | HistoryReport | null): string {
  return task?.content ?? ''
}
function getReasoning(task: ActiveTask | HistoryReport | null): string {
  return task?.reasoning ?? ''
}
function getCompletion(task: ActiveTask | HistoryReport | null): { complete: boolean; truncated: boolean } {
  if (!task || !('complete' in task)) return { complete: true, truncated: false }
  return { complete: task.complete !== false, truncated: task.truncated === true }
}
function getMeta(task: ActiveTask | HistoryReport | null) {
  if (!task) return null
  if ('meta' in task) return task.meta
  return { summary: task.summary, close: task.close, levels: task.levels }
}

export function StockAnalysisDialog({ task, mode, minimized }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [focus, setFocus] = useState('')
  const [copied, setCopied] = useState(false)
  const [reasoningOpen, setReasoningOpen] = useState(false)
  /** 放大态:默认大尺寸(1200px × 85vh) ↔ 近全屏(96vw × 94vh) */
  const [expanded, setExpanded] = useState(false)

  const phase = getPhase(task)
  const content = getContent(task)
  const reasoning = getReasoning(task)
  const completion = getCompletion(task)
  const meta = getMeta(task)
  const isHistory = mode === 'history'
  const isWorking = phase === 'loading' || phase === 'streaming'
  const open = !!task && !minimized
  const taskId = task && 'id' in task ? task.id : null

  useEffect(() => {
    if (open && phase === 'streaming' && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [content, phase, open])

  useEffect(() => {
    setFocus(task && 'focus' in task ? task.focus : '')
    setReasoningOpen(false)
  }, [taskId])

  const handleStartNew = useCallback(async () => {
    if (!task) return
    const name = 'name' in task ? task.name : ''
    await startAnalysis(task.symbol, name, focus.trim())
  }, [task, focus])

  const handleCopy = async () => {
    if (!content) return
    const success = await copyText(content)
    if (!success) {
      toast('复制失败,请手动选择文本', 'error')
      return
    }
    setCopied(true)
    toast('已复制到剪贴板', 'success')
    setTimeout(() => setCopied(false), 2000)
  }

  // 生成中禁止遮罩点击/ESC 关闭 (只能通过最小化气泡后台运行)
  if (!open) return null

  const error = task && 'error' in task ? task.error : ''

  return (
    <MantineModal
      opened
      onClose={closeDialog}
      withCloseButton={false}
      closeOnClickOutside={!isWorking}
      closeOnEscape={!isWorking}
      centered
      padding={0}
      transitionProps={{ duration: 150 }}
      overlayProps={{ backgroundOpacity: 0.5, blur: 4 }}
      classNames={{
        content: cn(
          'bg-surface/95 backdrop-blur-xl border border-border/50 rounded-2xl shadow-2xl flex flex-col overflow-hidden',
          expanded ? 'w-[96vw] max-w-[96vw] h-[94vh]' : 'w-full max-w-[1200px] h-[85vh]',
        ),
        body: 'flex min-h-0 flex-1 flex-col',
      }}
      styles={{ content: { flex: '0 1 auto' } }}
    >
          {/* 头部 —— 蓝色主题 */}
          <div className="relative px-5 py-3.5 border-b border-border/50 bg-gradient-to-r from-sky-500/[0.06] via-blue-500/[0.04] to-transparent">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500/20 to-blue-500/15 border border-sky-400/30 shrink-0">
                {isHistory
                  ? <History className="h-4.5 w-4.5 text-sky-300" />
                  : <LineChart className="h-4.5 w-4.5 text-sky-300" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-foreground truncate">
                    {isHistory ? '历史分析报告' : 'AI 个股分析'}
                  </span>
                  {task && <span className="text-xs text-secondary truncate">{task.name}</span>}
                  {task && <span className="text-[10px] font-mono text-muted shrink-0">{task.symbol}</span>}
                </div>
                <div className="flex items-center gap-2 mt-0.5 text-[10px] text-muted">
                  {meta?.summary ? (
                    <span className="flex items-center gap-1 truncate">
                      <Sparkles className="h-2.5 w-2.5 shrink-0" />
                      <span className="truncate">{meta.summary}</span>
                    </span>
                  ) : isWorking ? <span>正在读取行情与价位数据…</span> : null}
                  {phase === 'streaming' && (
                    <span className="flex items-center gap-1 text-sky-300 shrink-0">
                      <span className="h-1.5 w-1.5 rounded-full bg-sky-400 animate-pulse" />生成中
                    </span>
                  )}
                  {isHistory && task && 'created_at' in task && (
                    <span className="shrink-0">{fmtRelative(task.created_at)}</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {content && !isWorking && (
                  <button onClick={handleCopy} title="复制全文"
                    className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-foreground transition-colors">
                    {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                  </button>
                )}
                {!isHistory && isWorking && (
                  <button onClick={minimizeDialog} title="最小化为气泡,后台继续生成"
                    className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-foreground transition-colors">
                    <Minimize2 className="h-4 w-4" />
                  </button>
                )}
                <Tooltip label={expanded ? '还原默认尺寸' : '放大至近全屏'} position="bottom">
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    size="md"
                    onClick={() => setExpanded(v => !v)}
                    aria-label={expanded ? '还原默认尺寸' : '放大至近全屏'}
                  >
                    {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
                  </ActionIcon>
                </Tooltip>
                {(!isWorking || isHistory) && (
                  <button onClick={closeDialog} title="关闭"
                    className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-foreground transition-colors">
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* 内容区 */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 min-h-[280px]">
            {phase === 'loading' && !content && (
              <div className="flex flex-col items-center justify-center py-16 gap-3">
                <div className="relative">
                  <div className="h-10 w-10 rounded-full bg-gradient-to-br from-sky-500/20 to-blue-500/15 border border-sky-400/30 flex items-center justify-center">
                    <LineChart className="h-4.5 w-4.5 text-sky-300 animate-pulse" />
                  </div>
                  <Loader2 className="absolute -inset-1 h-12 w-12 text-sky-400/40 animate-spin" style={{ animationDuration: '3s' }} />
                </div>
                <div className="text-xs text-secondary">AI 正在分析行情与关键价位…</div>
                <div className="text-[10px] text-muted">读取日 K / 技术指标 / 压力支撑 / 财务,生成四维分析</div>
              </div>
            )}

            {phase === 'error' && (
              <div className="flex flex-col items-center justify-center py-14 gap-3">
                <div className="h-11 w-11 rounded-full bg-danger/10 flex items-center justify-center">
                  <AlertTriangle className="h-5 w-5 text-danger" />
                </div>
                <div className="text-sm font-medium text-foreground">分析失败</div>
                <div className="text-xs text-secondary text-center max-w-md px-4">{error}</div>
                {error.includes('AI') && (
                  <button onClick={() => { window.location.href = '/settings?tab=ai' }}
                    className="mt-1 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-elevated border border-border text-xs text-secondary hover:text-foreground transition-colors">
                    <Settings2 className="h-3.5 w-3.5" /> 去配置 AI
                  </button>
                )}
                <button onClick={handleStartNew}
                  className="mt-1 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-sky-500/15 border border-sky-400/30 text-xs text-sky-300 hover:bg-sky-500/20 transition-colors">
                  <RefreshCw className="h-3.5 w-3.5" /> 重试
                </button>
              </div>
            )}

            {(content || phase === 'streaming') && (
              <div className="relative">
                {reasoning && (
                  <div className="mb-4 rounded-lg border border-border/60 bg-elevated/40">
                    <button
                      type="button"
                      aria-expanded={reasoningOpen}
                      onClick={() => setReasoningOpen(openState => !openState)}
                      className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[11px] text-secondary transition-colors hover:text-foreground"
                    >
                      <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', reasoningOpen && 'rotate-90')} />
                      <span>思考过程（模型草稿）</span>
                      {task && 'continuing' in task && task.continuing && <span className="text-sky-300">正在补齐回答…</span>}
                    </button>
                    {reasoningOpen && (
                      <div className="border-t border-border/50 px-3 py-2 text-[11px] leading-relaxed text-muted whitespace-pre-wrap">
                        {reasoning}
                      </div>
                    )}
                  </div>
                )}
                {reasoning && <div className="mb-2 text-[11px] font-medium text-foreground/70">回答</div>}
                <MarkdownRenderer content={content} />
                {phase === 'streaming' && (
                  <span className="inline-block w-1.5 h-3.5 bg-sky-400 ml-0.5 align-middle animate-pulse rounded-sm" />
                )}
                {(!completion.complete || completion.truncated) && (
                  <div className="mt-4 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-[11px] leading-relaxed text-warning">
                    回答达到模型输出上限，当前内容可能未完整生成，请点击“重新分析”补齐。
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 底部:关注点输入 */}
          <div className="border-t border-border/50 bg-surface/60 px-5 py-3">
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 text-[10px] text-muted shrink-0">
                <Wand2 className="h-3 w-3" />
                <span className="hidden sm:inline">关注重点</span>
              </div>
              <input
                type="text"
                value={focus}
                onChange={e => setFocus(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && (phase === 'done' || phase === 'error' || isHistory)) handleStartNew() }}
                disabled={isWorking}
                placeholder={isHistory ? '修改关注重点,回车重新生成' : (phase === 'done' ? '如:重点看能否突破压力位…回车重新分析' : '可留空,留空则全面分析')}
                className={cn(
                  'flex-1 h-8 px-3 rounded-lg bg-base ring-1 ring-border/30 text-xs text-foreground placeholder:text-muted/40',
                  'focus:outline-none focus:ring-2 focus:ring-sky-400/30 transition-shadow disabled:opacity-50',
                )}
              />
              {isHistory ? (
                <button
                  onClick={handleStartNew}
                  className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-gradient-to-r from-sky-500/20 to-blue-500/15 border border-sky-400/30 text-xs font-medium text-sky-300 hover:from-sky-500/30 hover:to-blue-500/20 transition-all shrink-0"
                  title="以此关注点重新生成新报告"
                >
                  <RefreshCw className="h-3.5 w-3.5" />重新生成
                </button>
              ) : (
                <button
                  onClick={handleStartNew}
                  disabled={isWorking}
                  className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-gradient-to-r from-sky-500/20 to-blue-500/15 border border-sky-400/30 text-xs font-medium text-sky-300 hover:from-sky-500/30 hover:to-blue-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all shrink-0"
                  title={focus.trim() ? '按关注重点重新分析' : '重新分析'}
                >
                  {isWorking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : phase === 'done' ? <RefreshCw className="h-3.5 w-3.5" /> : <Send className="h-3.5 w-3.5" />}
                  {phase === 'done' ? '重新分析' : '分析'}
                </button>
              )}
            </div>
            <p className="mt-1.5 text-[10px] text-muted/50 leading-relaxed">
              {isHistory
                ? '历史报告为静态记录;修改关注重点后将作为新任务重新生成。报告仅供参考,不构成投资建议。'
                : '报告由项目已配置的 AI 模型基于本地行情与财务数据生成;消息面维度暂依据价量异动推断。报告仅供参考,不构成投资建议。'}
            </p>
          </div>
    </MantineModal>
  )
}

function fmtRelative(iso: string): string {
  try {
    const t = new Date(iso).getTime()
    const diff = Date.now() - t
    if (diff < 60_000) return '刚刚'
    if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`
    if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`
    if (diff < 7 * 86400_000) return `${Math.floor(diff / 86400_000)} 天前`
    return new Date(iso).toLocaleDateString('zh-CN')
  } catch { return '' }
}
