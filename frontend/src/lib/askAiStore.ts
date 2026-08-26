import { useSyncExternalStore } from 'react'
import { api } from './api'
import { accountStorage } from './storage'

export type AskPhase = 'loading' | 'streaming' | 'done' | 'error'
export interface AskMessage { role: 'user' | 'assistant'; content: string }
export interface AskToolEvent { call_id: string; tool_name: string; label: string; state: 'running' | 'done' | 'failed' }
export interface AskTask {
  id: string
  scopeKey: string
  symbol: string
  name: string
  context: string
  suggestions: string[]
  messages: AskMessage[]
  content: string
  phase: AskPhase
  error: string
  tools: AskToolEvent[]
  complete: boolean
  truncated: boolean
  dismissed?: boolean
}

const MAX_ACTIVE = 3
// 复用老版本的命名空间，让同一浏览器里的旧问答记录可以继续使用。
const STORAGE_PREFIX = 'vr-askai-chat:'
const STORAGE_VERSION = 1
let tasks: AskTask[] = []
const controllers = new Map<string, AbortController>()
let dialogTaskId: string | null = null
let minimized = false
const listeners = new Set<() => void>()
let taskSnap: AskTask[] = []
interface DialogSnapshot { taskId: string | null; minimized: boolean }
let dialogSnap: DialogSnapshot = { taskId: dialogTaskId, minimized }

function emit() { listeners.forEach(listener => listener()) }
function subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener) }
function rebuild() { taskSnap = tasks; dialogSnap = { taskId: dialogTaskId, minimized } }
function conversationId(scopeKey: string): string {
  const encoded = encodeURIComponent(scopeKey).replace(/%/g, '_')
  return `ask_${encoded.slice(0, 70)}`
}
function storageKey(scopeKey: string): string { return `${STORAGE_PREFIX}${scopeKey}` }
function readStoredMessages(scopeKey: string): AskMessage[] {
  try {
    const raw = accountStorage.getItem(storageKey(scopeKey))
    if (!raw) return []
    const parsed = JSON.parse(raw) as { version?: number; messages?: unknown }
    if (parsed.version !== STORAGE_VERSION && parsed.version !== 2) return []
    const stored = parsed.messages
    if (!Array.isArray(stored)) return []
    return stored.filter((message: unknown): message is AskMessage => {
      if (!message || typeof message !== 'object') return false
      const value = message as Record<string, unknown>
      return (value.role === 'user' || value.role === 'assistant') && typeof value.content === 'string'
    }).slice(-40)
  } catch { return [] }
}
function saveStoredMessages(task: AskTask) {
  try {
    accountStorage.setItem(storageKey(task.scopeKey), JSON.stringify({
      version: STORAGE_VERSION,
      updatedAt: Date.now(),
      messages: task.messages.slice(-40),
    }))
  } catch { /* localStorage unavailable */ }
}
function removeStoredMessages(scopeKey: string) {
  try { accountStorage.removeItem(storageKey(scopeKey)) } catch { /* ignore */ }
}
function patchTask(id: string, patch: Partial<AskTask>) {
  tasks = tasks.map(task => task.id === id ? { ...task, ...patch } : task)
  rebuild(); emit()
}
function getTasks() { return taskSnap }
function getDialog() { return dialogSnap }

export function useAskBubbleTasks() {
  const all = useSyncExternalStore(subscribe, getTasks, () => [])
  useSyncExternalStore(subscribe, getDialog, () => ({ taskId: null, minimized: false }))
  return all.filter(task => {
    if ((task.phase === 'loading' || task.phase === 'streaming') && dialogSnap.taskId === task.id && !dialogSnap.minimized) return false
    if (task.dismissed && task.phase !== 'loading' && task.phase !== 'streaming') return false
    return !(dialogSnap.taskId === task.id && !dialogSnap.minimized)
  })
}

export function useAskDialogState() {
  return useSyncExternalStore(subscribe, getDialog, () => ({ taskId: null, minimized: false }))
}

export function useAskDialogTask() {
  const state = useAskDialogState()
  const all = useSyncExternalStore(subscribe, getTasks, () => [])
  return state.taskId ? all.find(task => task.id === state.taskId) ?? null : null
}

/** 打开一个页面级持久会话，不自动发送问题。 */
export function openAskAi(
  scopeKey: string,
  symbol = '',
  name = '',
  context = '',
  suggestions: string[] = [],
): { id?: string; error?: string } {
  const existing = tasks.find(task => task.scopeKey === scopeKey)
  if (existing) {
    patchTask(existing.id, { symbol, name, context, suggestions })
    openAskDialog(existing.id)
    return { id: existing.id }
  }
  const task: AskTask = {
    id: conversationId(scopeKey),
    scopeKey,
    symbol,
    name,
    context,
    suggestions,
    messages: readStoredMessages(scopeKey),
    content: '',
    phase: 'done',
    error: '',
    tools: [],
    complete: true,
    truncated: false,
  }
  tasks = [...tasks, task]
  dialogTaskId = task.id
  minimized = false
  rebuild(); emit()
  return { id: task.id }
}

/** 兼容行情条/财务详情里的紧凑入口：打开对应股票会话，不强制替用户发问。 */
export function startAskAi(symbol: string, name: string, context = ''): { id?: string; error?: string } {
  const scopeKey = `stock:${symbol || 'market'}`
  const active = tasks.find(task => task.scopeKey === scopeKey && (task.phase === 'loading' || task.phase === 'streaming'))
  if (active) { openAskDialog(active.id); return { id: active.id } }
  const running = tasks.filter(task => task.phase === 'loading' || task.phase === 'streaming')
  if (running.length >= MAX_ACTIVE) return { error: `同时进行的问 AI 任务不能超过 ${MAX_ACTIVE} 个` }
  return openAskAi(scopeKey, symbol, name, context, ['这只股票当前的客观状态是什么？', '最近数据有哪些值得注意的变化？', '目前有哪些数据缺口？'])
}

export function sendAskMessage(id: string, content: string) {
  const text = content.trim()
  const task = tasks.find(item => item.id === id)
  if (!task || !text || task.phase === 'loading' || task.phase === 'streaming') return
  const messages = [...task.messages, { role: 'user' as const, content: text }]
  patchTask(id, { messages, content: '', phase: 'loading', error: '', tools: [], dismissed: false })
  const controller = new AbortController()
  controllers.set(id, controller)
  void runStream(id, controller.signal)
}

async function runStream(id: string, signal: AbortSignal) {
  const task = tasks.find(item => item.id === id)
  if (!task) return
  try {
    let content = ''
    let sawDone = false
    for await (const event of api.chatStream({
      messages: task.messages,
      context: task.context,
      stock_code: task.symbol || undefined,
      stock_name: task.name || undefined,
      conversation_id: task.id,
    }, signal)) {
      const current = tasks.find(item => item.id === id)
      if (!current) return
      if (event.type === 'delta') {
        content += event.text ?? ''
        patchTask(id, { phase: 'streaming', content })
      } else if (event.type === 'tool_started' && event.call_id) {
        patchTask(id, {
          tools: [...current.tools.filter(tool => tool.call_id !== event.call_id), {
            call_id: event.call_id,
            tool_name: event.tool_name ?? '',
            label: event.label ?? event.tool_name ?? '工具',
            state: 'running',
          }],
        })
      } else if ((event.type === 'tool_completed' || event.type === 'tool_failed') && event.call_id) {
        patchTask(id, { tools: current.tools.map(tool => tool.call_id === event.call_id ? { ...tool, state: event.type === 'tool_completed' ? 'done' : 'failed' } : tool) })
      } else if (event.type === 'error') {
        patchTask(id, { phase: 'error', error: event.message ?? '问 AI 失败' })
        return
      } else if (event.type === 'done') {
        sawDone = true
        const completed = tasks.find(item => item.id === id)
        const complete = event.complete !== false
        const truncated = event.truncated === true
        const nextMessages = completed && content && complete && !truncated
          ? [...completed.messages, { role: 'assistant' as const, content }]
          : completed?.messages ?? []
        patchTask(id, { content, messages: nextMessages, phase: 'done', error: '', complete, truncated })
        const saved = tasks.find(item => item.id === id)
        if (saved && complete && !truncated) saveStoredMessages(saved)
        controllers.delete(id)
      }
    }
    controllers.delete(id)
    const final = tasks.find(item => item.id === id)
    if (final && !sawDone && final.phase !== 'error') {
      patchTask(id, { phase: 'error', error: '问 AI 连接在完成前断开，请重试', complete: false, truncated: false })
    } else if (final && final.phase !== 'error' && final.phase !== 'done') {
      patchTask(id, { phase: content ? 'done' : 'error', error: content ? '' : 'AI 未返回内容', complete: !!content, truncated: false })
      const saved = tasks.find(item => item.id === id)
      if (saved && content) saveStoredMessages(saved)
    }
  } catch (error: any) {
    controllers.delete(id)
    if (signal.aborted) return
    patchTask(id, { phase: 'error', error: String(error?.message ?? '问 AI 失败') })
  }
}

/** Stop old-account streams and clear all in-memory private conversations. */
export function resetAccountState(): void {
  for (const controller of controllers.values()) controller.abort()
  controllers.clear()
  tasks = []
  dialogTaskId = null
  minimized = false
  rebuild()
  emit()
}

export function clearAskConversation(id: string) {
  const task = tasks.find(item => item.id === id)
  if (!task) return
  controllers.get(id)?.abort()
  controllers.delete(id)
  removeStoredMessages(task.scopeKey)
  patchTask(id, { messages: [], content: '', phase: 'done', error: '', tools: [], dismissed: false })
}

export function openAskDialog(id: string) { dialogTaskId = id; minimized = false; rebuild(); emit() }
export function minimizeAskDialog() { minimized = true; rebuild(); emit() }
export function closeAskDialog() { dialogTaskId = null; minimized = false; rebuild(); emit() }
export function restoreAskDialog(id: string) { patchTask(id, { dismissed: false }); openAskDialog(id) }
