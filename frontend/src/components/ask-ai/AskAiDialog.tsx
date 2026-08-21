import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Bot, Loader2, Send, Sparkles, Trash2, X } from 'lucide-react'
import type { AskTask } from '@/lib/askAiStore'
import { clearAskConversation, closeAskDialog, sendAskMessage } from '@/lib/askAiStore'
import { MarkdownRenderer } from '@/components/financials/MarkdownRenderer'

export function AskAiDialog({ task, minimized }: { task: AskTask | null; minimized: boolean }) {
  const [input, setInput] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [task?.content, task?.messages.length, task?.tools.length])
  if (!task || minimized) return null
  const busy = task.phase === 'loading' || task.phase === 'streaming'
  const submit = (text = input) => {
    if (!text.trim() || busy) return
    sendAskMessage(task.id, text)
    setInput('')
  }
  const hasMessages = task.messages.length > 0 || !!task.content
  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-black/45" onClick={closeAskDialog}>
      <aside className="relative m-3 flex h-[calc(100vh-24px)] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl" onClick={event => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <Sparkles className="h-4 w-4 text-accent" />
              <span className="truncate">问 AI{task.name ? ` · ${task.name}` : ' · 本页上下文'}</span>
            </div>
            <div className="mt-0.5 text-[10px] text-muted">当前页面数据会自动注入；只输出客观研究，不提供买卖指令</div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {task.messages.length > 0 && (
              <button type="button" onClick={() => clearAskConversation(task.id)} title="清空本页对话" aria-label="清空本页对话" className="rounded p-1 text-muted transition-colors hover:bg-elevated hover:text-foreground">
                <Trash2 className="h-4 w-4" />
              </button>
            )}
            <button type="button" onClick={closeAskDialog} title="关闭" aria-label="关闭" className="rounded p-1 text-muted transition-colors hover:bg-elevated hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4 text-xs">
          {!hasMessages && (
            <>
              <div className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs leading-relaxed text-secondary">
                <div className="mb-1 flex items-center gap-1.5 font-medium text-foreground"><Bot className="h-3.5 w-3.5 text-accent" />本页上下文已准备好</div>
                你可以直接提问，AI 会结合当前页面已接入的行情、K 线、财务、概念或市场数据回答；没有接入的数据会明确标注。
              </div>
              {task.suggestions.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {task.suggestions.map(suggestion => (
                    <button key={suggestion} type="button" onClick={() => submit(suggestion)} disabled={busy} className="rounded-full border border-border bg-elevated/50 px-2.5 py-1.5 text-[11px] text-secondary transition-colors hover:border-accent/40 hover:text-accent disabled:opacity-40">
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
          {task.messages.map((message, index) => (
            <div key={`${index}-${message.role}`} className={message.role === 'user' ? 'ml-8 rounded-2xl bg-accent/10 px-3 py-2.5 text-foreground' : 'mr-4 rounded-2xl bg-elevated/60 px-3 py-2.5 text-secondary'}>
              {message.role === 'assistant' ? <MarkdownRenderer content={message.content} /> : message.content}
            </div>
          ))}
          {task.content && task.messages[task.messages.length - 1]?.role === 'user' && (
            <div className="mr-4 rounded-2xl bg-elevated/60 px-3 py-2.5 text-secondary"><MarkdownRenderer content={task.content} /></div>
          )}
          {task.tools.length > 0 && (
            <div className="space-y-1 text-[10px] text-muted">
              {task.tools.map(tool => <div key={tool.call_id}>{tool.state === 'running' ? '⏳' : tool.state === 'failed' ? '⚠' : '✓'} {tool.label}</div>)}
            </div>
          )}
          {busy && <div className="flex items-center gap-2 text-xs text-muted"><Loader2 className="h-3.5 w-3.5 animate-spin" />AI 正在思考 / 调取数据…</div>}
          {task.phase === 'error' && <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger/5 p-2 text-xs text-danger"><AlertCircle className="h-3.5 w-3.5 shrink-0" />{task.error}</div>}
          <div ref={endRef} />
        </div>

        <div className="border-t border-border/60 p-3">
          <div className="flex items-end gap-2 rounded-xl border border-border bg-elevated/40 p-2 focus-within:border-accent/60">
            <textarea
              value={input}
              onChange={event => setInput(event.target.value)}
              onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit() } }}
              disabled={busy}
              rows={2}
              placeholder="就本页内容提问…"
              className="min-h-[42px] flex-1 resize-none bg-transparent px-1 py-1 text-xs text-foreground outline-none placeholder:text-muted"
            />
            <button type="button" onClick={() => submit()} disabled={busy || !input.trim()} className="rounded-lg bg-accent p-2 text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40" title="发送"><Send className="h-4 w-4" /></button>
          </div>
          <div className="mt-1 flex items-center justify-between text-[10px] text-muted"><span>Shift+Enter 换行</span><span>数据缺口会明确说明</span></div>
        </div>
      </aside>
    </div>
  )
}
