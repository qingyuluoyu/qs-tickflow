import { useSyncExternalStore } from 'react'
import { api } from './api'

export type AskPhase = 'loading' | 'streaming' | 'done' | 'error'
export interface AskMessage { role: 'user' | 'assistant'; content: string }
export interface AskToolEvent { call_id: string; tool_name: string; label: string; state: 'running' | 'done' | 'failed' }
export interface AskTask {
  id: string
  symbol: string
  name: string
  context: string
  messages: AskMessage[]
  content: string
  phase: AskPhase
  error: string
  tools: AskToolEvent[]
  dismissed?: boolean
}

const MAX_ACTIVE = 3
let tasks: AskTask[] = []
let dialogTaskId: string | null = null
let minimized = false
const listeners = new Set<() => void>()
let taskSnap: AskTask[] = []
let dialogSnap = { taskId: dialogTaskId, minimized }
function emit() { listeners.forEach(listener => listener()) }
function subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener) }
function rebuild() { taskSnap = tasks; dialogSnap = { taskId: dialogTaskId, minimized } }
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

export function startAskAi(symbol: string, name: string, context = ''): { id?: string; error?: string } {
  const existing = tasks.find(task => task.symbol === symbol && (task.phase === 'loading' || task.phase === 'streaming'))
  if (existing) { openAskDialog(existing.id); return { id: existing.id } }
  if (tasks.filter(task => task.phase === 'loading' || task.phase === 'streaming').length >= MAX_ACTIVE) {
    return { error: `同时进行的问 AI 任务不能超过 ${MAX_ACTIVE} 个` }
  }
  const id = `ask_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const initial: AskMessage = { role: 'user', content: '请基于当前已接入的数据，给出这只股票的客观状态概览。' }
  const task: AskTask = { id, symbol, name, context, messages: [initial], content: '', phase: 'loading', error: '', tools: [] }
  tasks = [...tasks, task]; dialogTaskId = id; minimized = false; rebuild(); emit()
  void runStream(id)
  return { id }
}

export function sendAskMessage(id: string, content: string) {
  const text = content.trim()
  const task = tasks.find(item => item.id === id)
  if (!task || !text || task.phase === 'loading' || task.phase === 'streaming') return
  const messages = [...task.messages, { role: 'user' as const, content: text }]
  patchTask(id, { messages, content: '', phase: 'loading', error: '', tools: [] })
  void runStream(id)
}

async function runStream(id: string) {
  const task = tasks.find(item => item.id === id)
  if (!task) return
  try {
    let content = ''
    for await (const event of api.chatStream({
      messages: task.messages,
      context: task.context,
      stock_code: task.symbol,
      stock_name: task.name,
      conversation_id: id,
    })) {
      const current = tasks.find(item => item.id === id)
      if (!current) return
      if (event.type === 'delta') {
        content += event.text ?? ''
        patchTask(id, { phase: 'streaming', content })
      } else if (event.type === 'tool_started' && event.call_id) {
        patchTask(id, { tools: [...current.tools.filter(tool => tool.call_id !== event.call_id), { call_id: event.call_id, tool_name: event.tool_name ?? '', label: event.label ?? event.tool_name ?? '工具', state: 'running' }] })
      } else if ((event.type === 'tool_completed' || event.type === 'tool_failed') && event.call_id) {
        patchTask(id, { tools: current.tools.map(tool => tool.call_id === event.call_id ? { ...tool, state: event.type === 'tool_completed' ? 'done' : 'failed' } : tool) })
      } else if (event.type === 'error') {
        patchTask(id, { phase: 'error', error: event.message ?? '问 AI 失败' })
        return
      } else if (event.type === 'done') {
        const completed = tasks.find(item => item.id === id)
        if (completed && content) patchTask(id, { phase: 'done', content, messages: [...completed.messages, { role: 'assistant', content }] })
        else patchTask(id, { phase: 'done', content })
      }
    }
    const final = tasks.find(item => item.id === id)
    if (final && final.phase !== 'error' && final.phase !== 'done') patchTask(id, { phase: content ? 'done' : 'error', error: content ? '' : 'AI 未返回内容' })
  } catch (error: any) {
    patchTask(id, { phase: 'error', error: String(error?.message ?? '问 AI 失败') })
  }
}

export function openAskDialog(id: string) { dialogTaskId = id; minimized = false; rebuild(); emit() }
export function minimizeAskDialog() { minimized = true; rebuild(); emit() }
export function closeAskDialog() { dialogTaskId = null; minimized = false; rebuild(); emit() }
export function restoreAskDialog(id: string) { patchTask(id, { dismissed: true }); openAskDialog(id) }
