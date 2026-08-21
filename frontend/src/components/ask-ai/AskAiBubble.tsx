import { Bot, Check, Loader2, MessageCircle, X } from 'lucide-react'
import { useAskBubbleTasks, openAskDialog } from '@/lib/askAiStore'

export function AskAiBubble() {
  const tasks = useAskBubbleTasks()
  if (!tasks.length) return null
  return (
    <div className="fixed bottom-20 right-4 z-[65] flex w-52 flex-col gap-1.5">
      {tasks.map(task => (
        <button
          key={task.id}
          type="button"
          onClick={() => openAskDialog(task.id)}
          className="flex items-center gap-2 rounded-xl border border-accent/30 bg-surface/95 px-3 py-2 text-left text-xs shadow-xl backdrop-blur transition hover:border-accent/60"
        >
          {task.phase === 'loading' || task.phase === 'streaming' ? <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" /> : task.phase === 'error' ? <X className="h-3.5 w-3.5 text-danger" /> : <Check className="h-3.5 w-3.5 text-bull" />}
          <span className="min-w-0 flex-1 truncate text-foreground">{task.name || task.symbol}</span>
          <MessageCircle className="h-3.5 w-3.5 text-muted" />
        </button>
      ))}
      <div className="flex items-center gap-1 px-1 text-[10px] text-muted"><Bot className="h-3 w-3" />问 AI 任务</div>
    </div>
  )
}
