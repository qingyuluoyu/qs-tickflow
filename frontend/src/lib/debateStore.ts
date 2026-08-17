import { useSyncExternalStore } from 'react'
import { api } from './api'

export type DebatePhase = 'loading' | 'dossier' | 'streaming' | 'done' | 'error'
export interface DebateStage { stage: string; label: string; content: string; done: boolean; failed?: boolean }
export interface DebateTask {
  id: string
  code: string
  name: string
  rounds: number
  phase: DebatePhase
  status: string
  loaded: number
  total: number
  sections: Array<{ title: string; tool: string; ok?: boolean }>
  missing: string[]
  stages: DebateStage[]
  error: string
  createdAt: number
}

const MAX_ACTIVE = 3
let tasks: DebateTask[] = []
const listeners = new Set<() => void>()
let snapshot: DebateTask[] = tasks
function emit() { snapshot = tasks; listeners.forEach(fn => fn()) }
function subscribe(fn: () => void) { listeners.add(fn); return () => listeners.delete(fn) }
function getSnapshot() { return snapshot }
function patchTask(id: string, patch: Partial<DebateTask>) {
  tasks = tasks.map(task => task.id === id ? { ...task, ...patch } : task)
  emit()
}

export function useDebateTasks() {
  return useSyncExternalStore(subscribe, getSnapshot, () => [])
}

export function startDebate(code: string, name: string, rounds: number): { id?: string; error?: string } {
  const existing = tasks.find(t => t.code === code && (t.phase === 'loading' || t.phase === 'dossier' || t.phase === 'streaming'))
  if (existing) return { id: existing.id }
  const ongoing = tasks.filter(t => t.phase === 'loading' || t.phase === 'dossier' || t.phase === 'streaming')
  if (ongoing.length >= MAX_ACTIVE) return { error: `同时进行的辩论任务不能超过 ${MAX_ACTIVE} 个` }
  const id = `debate_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  tasks = [...tasks, {
    id, code, name, rounds, phase: 'loading', status: '准备开始', loaded: 0, total: 5,
    sections: [], missing: [], stages: [], error: '', createdAt: Date.now(),
  }]
  emit()
  void runStream(id, code, rounds)
  return { id }
}

async function runStream(id: string, code: string, rounds: number) {
  try {
    for await (const event of api.debateStream(code, rounds)) {
      const task = tasks.find(t => t.id === id)
      if (!task) return
      if (event.type === 'status') patchTask(id, { phase: 'dossier', status: event.message ?? '正在准备底稿' })
      else if (event.type === 'dossier_progress') {
        patchTask(id, { phase: 'dossier', status: `底稿：${event.title ?? ''}`, loaded: event.loaded ?? task.loaded, total: event.total ?? task.total })
      } else if (event.type === 'dossier') {
        patchTask(id, { phase: 'dossier', status: '客观事实底稿已就绪', sections: (event.sections ?? []).map(s => ({ ...s })), missing: event.missing ?? [] })
      } else if (event.type === 'stage') {
        const stages = task.stages.some(s => s.stage === event.stage)
          ? task.stages
          : [...task.stages, { stage: event.stage ?? '', label: event.label ?? event.stage ?? '', content: '', done: false }]
        patchTask(id, { phase: 'streaming', status: event.label ?? '正在生成', stages })
      } else if (event.type === 'delta' && event.stage) {
        const stages = task.stages.map(s => s.stage === event.stage ? { ...s, content: s.content + (event.text ?? '') } : s)
        patchTask(id, { phase: 'streaming', stages })
      } else if (event.type === 'stage_done' && event.stage) {
        const stages = task.stages.map(s => s.stage === event.stage ? { ...s, content: event.content ?? s.content, done: true, failed: event.failed } : s)
        patchTask(id, { phase: 'streaming', status: `${event.label ?? event.stage}已完成`, stages })
      } else if (event.type === 'error') {
        patchTask(id, { phase: 'error', error: event.message ?? '辩论失败', status: '生成失败' })
      } else if (event.type === 'done') {
        patchTask(id, { phase: 'done', status: '辩论完成' })
      }
    }
    const final = tasks.find(t => t.id === id)
    if (final && final.phase !== 'error' && final.phase !== 'done') patchTask(id, { phase: 'error', error: '流式响应提前结束', status: '生成失败' })
  } catch (error) {
    patchTask(id, { phase: 'error', error: String((error as Error)?.message ?? error), status: '生成失败' })
  }
}

export function clearFinishedDebates() {
  tasks = tasks.filter(t => t.phase === 'loading' || t.phase === 'dossier' || t.phase === 'streaming')
  emit()
}

