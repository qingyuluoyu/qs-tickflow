import { Sparkles } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { openAskAi } from '@/lib/askAiStore'

interface Props {
  context: string
  suggestions?: string[]
  label?: string
  scopeKey?: string
  symbol?: string
  name?: string
}

/** 老版本的页面级入口：按钮始终显示，点击后打开当前页面的持久问答会话。 */
export function AskAiButton({ context, suggestions = [], label = '问 AI', scopeKey = 'general', symbol = '', name = '' }: Props) {
  const { pathname } = useLocation()
  const conversationKey = `${pathname}#${scopeKey}`
  return (
    <button
      type="button"
      onClick={() => openAskAi(conversationKey, symbol, name, context, suggestions)}
      className="inline-flex items-center gap-1.5 rounded-btn border border-accent/35 bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent shadow-sm transition-colors hover:border-accent/60 hover:bg-accent/20"
      title="打开当前页面的问 AI 对话"
    >
      <Sparkles className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}
