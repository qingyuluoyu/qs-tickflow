import { useState } from 'react'
import { Loader2, Swords, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { StockFinancialSearch } from '@/components/financials/StockFinancialSearch'
import { MarkdownRenderer } from '@/components/financials/MarkdownRenderer'
import { toast } from '@/components/Toast'
import { clearFinishedDebates, startDebate, useDebateTasks } from '@/lib/debateStore'

export function Debate() {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [rounds, setRounds] = useState(1)
  const tasks = useDebateTasks()
  const current = tasks[tasks.length - 1]
  const select = (symbol: string, stockName: string) => { setCode(symbol); setName(stockName) }
  const begin = () => {
    if (!code) { toast('请先选择一只股票', 'error'); return }
    const result = startDebate(code, name, rounds)
    if (result.error) toast(result.error, 'error')
  }

  return (
    <>
      <PageHeader title="多空辩论" subtitle="同一份客观底稿 · 多方 · 空方 · 中立主持" right={
        <button onClick={clearFinishedDebates} className="inline-flex items-center gap-1.5 text-xs text-muted hover:text-foreground">
          <Trash2 className="h-3.5 w-3.5" /> 清理已完成
        </button>
      } />
      <div className="w-full px-8 py-6 space-y-5">
        <div className="flex flex-wrap items-center gap-3 rounded-card border border-border/60 bg-surface/40 p-4">
          <div className="w-80"><StockFinancialSearch onSelect={select} /></div>
          {code && <span className="text-xs text-secondary">{name || code} <span className="font-mono text-muted">{code}</span></span>}
          <label className="flex items-center gap-2 text-xs text-secondary">
            轮数
            <select value={rounds} onChange={e => setRounds(Number(e.target.value))} className="rounded border border-border bg-base px-2 py-1.5 text-xs">
              <option value={1}>1（多方 / 空方 / 主持）</option>
              <option value={2}>2（含交叉反驳）</option>
            </select>
          </label>
          <button onClick={begin} disabled={current?.phase === 'loading' || current?.phase === 'dossier' || current?.phase === 'streaming'} className="inline-flex items-center gap-1.5 rounded-btn border border-violet-400/30 bg-violet-500/15 px-3 py-1.5 text-xs font-medium text-violet-300 transition-colors hover:bg-violet-500/25 disabled:cursor-not-allowed disabled:opacity-40">
            <Swords className="h-3.5 w-3.5" /> 开始辩论
          </button>
        </div>

        {!current ? (
          <div className="flex flex-col items-center justify-center rounded-card border border-dashed border-border/60 py-24 text-center text-muted">
            <Swords className="mb-3 h-8 w-8 opacity-40" />
            <p className="text-sm">选择一只股票，生成基于同一事实底稿的多空讨论</p>
            <p className="mt-1 text-xs opacity-70">输出分歧与验证清单，不输出买卖结论</p>
          </div>
        ) : (
          <DebateResult task={current} />
        )}
      </div>
    </>
  )
}

function DebateResult({ task }: { task: ReturnType<typeof useDebateTasks>[number] }) {
  return (
    <div className="space-y-4">
      <div className="rounded-card border border-border/60 bg-surface/40 p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
          {task.phase === 'loading' || task.phase === 'dossier' || task.phase === 'streaming' ? <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> : <Swords className="h-4 w-4 text-violet-400" />}
          <span>{task.name || task.code}</span><span className="font-mono text-xs text-muted">{task.code}</span>
          <span className="ml-auto text-xs text-secondary">{task.status}</span>
        </div>
        {task.phase === 'dossier' && <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-elevated"><div className="h-full rounded-full bg-violet-400 transition-all" style={{ width: `${Math.min(100, task.total ? task.loaded / task.total * 100 : 0)}%` }} /></div>}
        {task.sections.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{task.sections.map(section => <span key={section.title} className="rounded bg-elevated px-2 py-1 text-[11px] text-secondary">{section.title}</span>)}</div>}
        {task.missing.length > 0 && <p className="mt-2 text-[11px] text-muted">数据缺口：{task.missing.join('、')}</p>}
        {task.error && <p className="mt-3 rounded bg-danger/10 px-3 py-2 text-xs text-danger">{task.error}</p>}
      </div>
      {task.stages.map(stage => (
        <section key={stage.stage} className="rounded-card border border-border/60 bg-surface/40 p-5">
          <div className="mb-3 flex items-center gap-2 border-b border-border/40 pb-2 text-sm font-medium"><span className="h-2 w-2 rounded-full bg-violet-400" />{stage.label}{!stage.done && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted" />}</div>
          {stage.content ? <MarkdownRenderer content={stage.content} /> : <p className="text-xs text-muted">正在生成…</p>}
        </section>
      ))}
    </div>
  )
}

