import { useEffect, useRef, useState } from 'react'
import { Loader2, Minus, Send, X } from 'lucide-react'
import type { AskTask } from '@/lib/askAiStore'
import { closeAskDialog, minimizeAskDialog, sendAskMessage } from '@/lib/askAiStore'
import { MarkdownRenderer } from '@/components/financials/MarkdownRenderer'

export function AskAiDialog({ task, minimized }: { task: AskTask | null; minimized: boolean }) {
  const [input, setInput] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [task?.content, task?.messages.length])
  if (!task || minimized) return null
  const busy = task.phase === 'loading' || task.phase === 'streaming'
  const submit = () => {
    if (!input.trim() || busy) return
    sendAskMessage(task.id, input)
    setInput('')
  }
  return (
    <div className="fixed bottom-4 right-4 z-[64] flex h-[min(620px,calc(100vh-32px))] w-[min(520px,calc(100vw-32px))] flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold text-foreground">问 AI · {task.name || task.symbol}</div><div className="text-[10px] text-muted">客观数据研究助手</div></div>
        {busy && <Loader2 className="h-4 w-4 animate-spin text-accent" />}
        <button type="button" onClick={minimizeAskDialog} className="rounded p-1 text-muted hover:bg-elevated hover:text-foreground" title="最小化"><Minus className="h-4 w-4" /></button>
        <button type="button" onClick={closeAskDialog} className="rounded p-1 text-muted hover:bg-elevated hover:text-foreground" title="关闭"><X className="h-4 w-4" /></button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 text-xs">
        {task.messages.map((message, index) => (
          <div key={`${index}-${message.role}`} className={message.role === 'user' ? 'ml-8 rounded-xl bg-accent/10 px-3 py-2 text-foreground' : 'mr-4 rounded-xl bg-elevated/60 px-3 py-2 text-secondary'}>
            {message.role === 'assistant' ? <MarkdownRenderer content={message.content} /> : message.content}
          </div>
        ))}
        {task.content && task.messages[task.messages.length - 1]?.role === 'user' && (
          <div className="mr-4 rounded-xl bg-elevated/60 px-3 py-2 text-secondary"><MarkdownRenderer content={task.content} /></div>
        )}
        {task.tools.length > 0 && (
          <div className="space-y-1 text-[10px] text-muted">{task.tools.map(tool => <div key={tool.call_id}>{tool.state === 'running' ? '⏳' : tool.state === 'failed' ? '⚠' : '✓'} {tool.label}</div>)}</div>
        )}
        {task.phase === 'error' && <div className="rounded-lg bg-danger/10 px-3 py-2 text-danger">{task.error}</div>}
        <div ref={endRef} />
      </div>
      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2 rounded-xl border border-border bg-elevated/40 p-2 focus-within:border-accent/60">
          <textarea value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit() } }} disabled={busy} rows={2} placeholder="输入要了解的客观问题…" className="min-h-[42px] flex-1 resize-none bg-transparent px-1 py-1 text-xs text-foreground outline-none placeholder:text-muted" />
          <button type="button" onClick={submit} disabled={busy || !input.trim()} className="rounded-lg bg-accent p-2 text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40" title="发送"><Send className="h-4 w-4" /></button>
        </div>
        <div className="mt-1 text-[10px] text-muted">Shift+Enter 换行 · 不提供买卖指令</div>
      </div>
    </div>
  )
}
