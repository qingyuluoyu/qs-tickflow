import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Circle, Play, Swords, Square, X } from 'lucide-react'
import { ActionIcon, Button } from '@mantine/core'
import { Modal } from '@/components/Modal'
import { api, type StockDebateEvent } from '@/lib/api'

interface StageBox {
  stage: string
  label: string
  content: string
  done: boolean
  failed?: boolean
}

interface DebateDialogProps {
  symbol: string
  name?: string
  onClose: () => void
}

const STAGE_TONE: Record<string, string> = {
  bull: 'border-sky-400/35 bg-sky-400/[0.06]',
  bull_rebut: 'border-sky-400/25 bg-sky-400/[0.03]',
  bear: 'border-sky-500/45 bg-sky-500/[0.08]',
  bear_rebut: 'border-sky-500/30 bg-sky-500/[0.04]',
  referee: 'border-border bg-background/30',
}

export function DebateDialog({ symbol, name, onClose }: DebateDialogProps) {
  const [rounds, setRounds] = useState<1 | 2>(1)
  const [running, setRunning] = useState(false)
  const [status, setStatus] = useState('')
  const [progress, setProgress] = useState<Array<{ title: string; ok: boolean }>>([])
  const [missing, setMissing] = useState<string[]>([])
  const [stages, setStages] = useState<StageBox[]>([])
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  const reset = () => {
    setStatus('')
    setProgress([])
    setMissing([])
    setStages([])
    setError('')
  }

  const applyEvent = (event: StockDebateEvent) => {
    if (event.type === 'status') {
      setStatus(event.message ?? '')
    } else if (event.type === 'dossier_progress') {
      setProgress(items => [...items, { title: event.title ?? '', ok: event.ok === true }])
      setStatus(`正在准备客观事实底稿… ${event.loaded ?? 0}/${event.total ?? 0}`)
    } else if (event.type === 'dossier') {
      setMissing(event.missing ?? [])
      setStatus('底稿就绪，辩论开始')
    } else if (event.type === 'stage') {
      setStages(items => [...items, {
        stage: event.stage ?? '', label: event.label ?? '', content: '', done: false,
      }])
    } else if (event.type === 'delta' && event.stage) {
      setStages(items => items.map(item => item.stage === event.stage && !item.done
        ? { ...item, content: item.content + (event.text ?? '') }
        : item))
    } else if (event.type === 'stage_done' && event.stage) {
      setStages(items => items.map(item => item.stage === event.stage && !item.done
        ? {
            ...item,
            content: event.content ?? item.content,
            done: true,
            failed: event.failed === true,
          }
        : item))
    } else if (event.type === 'error') {
      setError(event.stage ? `${event.stage}：${event.message ?? '生成失败'}` : (event.message ?? '辩论失败'))
    } else if (event.type === 'done') {
      setStatus(event.failed_stages?.length
        ? `辩论完成，${event.failed_stages.length} 个阶段失败`
        : '辩论完成')
    }
  }

  const start = async () => {
    if (running) return
    reset()
    setRunning(true)
    setStatus('正在连接后端…')
    const controller = new AbortController()
    abortRef.current = controller
    try {
      let sawDone = false
      let sawError = false
      for await (const event of api.stockDebateStream(symbol, rounds, controller.signal)) {
        if (event.type === 'done') sawDone = true
        if (event.type === 'error') sawError = true
        applyEvent(event)
      }
      if (!sawDone && !sawError && !controller.signal.aborted) {
        setError('辩论连接在完成前断开，请重试')
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') {
        setStatus('已中止')
      } else {
        setError(caught instanceof Error ? caught.message : String(caught))
      }
    } finally {
      if (abortRef.current === controller) {
        setRunning(false)
        abortRef.current = null
      }
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    setRunning(false)
    setStatus('已中止')
  }

  const close = () => {
    abortRef.current?.abort()
    onClose()
  }

  return (
    <Modal
      onClose={close}
      labelledBy="stock-debate-title"
      panelClassName="flex max-h-[88vh] w-[96vw] max-w-4xl flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-2xl"
      overlayClassName="bg-black/50 backdrop-blur-sm"
    >
      <header className="flex items-center gap-3 border-b border-border/60 px-5 py-3.5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-sky-400/25 bg-sky-400/10 text-sky-300">
          <Swords className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 id="stock-debate-title" className="text-sm font-semibold text-foreground">多空辩论</h2>
            <span className="truncate text-xs text-secondary">{name || symbol}</span>
            <span className="shrink-0 font-mono text-[10px] text-muted">{symbol}</span>
          </div>
          <p className="mt-0.5 text-[10px] text-muted">同一份客观底稿，多方与空方分别陈述，中立主持只整理分歧和验证清单。</p>
        </div>
        <ActionIcon variant="subtle" color="gray" size="md" onClick={close} aria-label="关闭">
          <X className="h-4 w-4" />
        </ActionIcon>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-muted">辩论深度</label>
          <select
            value={rounds}
            onChange={event => setRounds(Number(event.target.value) as 1 | 2)}
            disabled={running}
            className="rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-sky-400/60"
          >
            <option value={1}>一轮 · 各自陈述（3 次模型调用）</option>
            <option value={2}>两轮 · 加交叉反驳（5 次模型调用）</option>
          </select>
          {running ? (
            <Button size="xs" variant="default" onClick={stop} leftSection={<Square className="h-3.5 w-3.5" />}>
              中止
            </Button>
          ) : (
            <Button size="xs" variant="light" color="blue" onClick={start} leftSection={<Play className="h-3.5 w-3.5" />}>
              开始辩论
            </Button>
          )}
        </div>

        <p className="mt-3 text-[11px] leading-relaxed text-muted">
          结果只做客观信息整理，不给买卖建议、目标价或仓位建议。数据源暂时不可用时会标记为缺口，不会让模型补写。
        </p>

        {status && <p className="mt-3 text-xs text-secondary">{status}</p>}
        {error && (
          <p className="mt-3 flex items-start gap-1.5 text-xs text-bear">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{error}
          </p>
        )}

        {progress.length > 0 && (
          <div className="mt-4 rounded-md border border-border/50 bg-background/25 p-3">
            <p className="mb-2 text-[11px] text-muted">双方使用同一份后端事实底稿：</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {progress.map(item => (
                <span key={item.title} className="inline-flex items-center gap-1 text-[11px] text-muted">
                  {item.ok
                    ? <CheckCircle2 className="h-3 w-3 text-sky-300" />
                    : <Circle className="h-3 w-3 text-muted/50" />}
                  {item.title}
                </span>
              ))}
            </div>
            {missing.length > 0 && (
              <p className="mt-2 text-[11px] text-sky-300">未取到：{missing.join('、')}（立论时不得臆测）</p>
            )}
          </div>
        )}

        <div className="mt-4 space-y-3">
          {stages.map(stage => (
            <section key={stage.stage} className={`rounded-lg border p-4 ${STAGE_TONE[stage.stage] ?? 'border-border bg-background/20'}`}>
              <div className="mb-2 flex items-center gap-2">
                <Swords className="h-3.5 w-3.5 text-muted" />
                <h3 className="text-xs font-semibold text-foreground">{stage.label}</h3>
                {!stage.done && <span className="animate-pulse text-[10px] text-muted">生成中…</span>}
                {stage.failed && <span className="text-[10px] text-bear">失败</span>}
              </div>
              <div className="whitespace-pre-wrap text-xs leading-6 text-secondary">
                {stage.content || '…'}
              </div>
            </section>
          ))}
        </div>

        {stages.length === 0 && !running && !error && (
          <div className="mt-4 flex flex-col items-center gap-2 rounded-lg border border-dashed border-border/60 py-12 text-center text-xs text-muted">
            <Swords className="h-8 w-8 text-muted/40" />
            点击“开始辩论”，后端会先拉取这只股票的事实底稿。
          </div>
        )}
      </div>
    </Modal>
  )
}
