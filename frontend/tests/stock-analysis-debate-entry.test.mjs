import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const pageSource = readFileSync(new URL('../src/pages/StockAnalysis.tsx', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
const debateDialogSource = readFileSync(new URL('../src/components/stock-analysis/DebateDialog.tsx', import.meta.url), 'utf8')

test('多空辩论入口只放在点位提醒右侧', () => {
  const alertIndex = pageSource.indexOf('点位提醒')
  const debateIndex = pageSource.indexOf('多空辩论')

  assert.ok(alertIndex >= 0, '应保留点位提醒入口')
  assert.ok(debateIndex > alertIndex, '多空辩论入口应位于点位提醒之后')
  assert.match(pageSource, /DebateDialog/)
})

test('多空辩论使用当前选中的标准 symbol，不引入独立 LLM 配置', () => {
  assert.match(pageSource, /symbol=\{symbol\}/)
  assert.doesNotMatch(pageSource, /localStorage.*vr-llm|llm\s*:/)
})

test('后端底稿等待期间使用任务状态而非伪连接状态，中止后立即解除运行态', () => {
  assert.match(debateDialogSource, /正在启动多空辩论/)
  assert.doesNotMatch(debateDialogSource, /正在连接后端/)
  assert.match(debateDialogSource, /abortRef\.current\?\.abort\(\)\s*\n\s*setRunning\(false\)/)
  assert.match(debateDialogSource, /event\.type === 'dossier_progress'/)
})

test('多空辩论使用富文本渲染兜底，不直接暴露 Markdown 标记', () => {
  assert.match(debateDialogSource, /import \{ MarkdownRenderer \}/)
  assert.match(debateDialogSource, /<MarkdownRenderer content=\{stage\.content\}/)
  assert.doesNotMatch(debateDialogSource, /\{stage\.content \|\| '…'\}/)
})

test('个股 AI 流支持 AbortSignal 且工作态提供停止入口', () => {
  const storeSource = readFileSync(new URL('../src/lib/stockAnalysisStore.ts', import.meta.url), 'utf8')
  const dialogSource = readFileSync(new URL('../src/components/stock-analysis/StockAnalysisDialog.tsx', import.meta.url), 'utf8')

  assert.match(apiSource, /stockAnalyzeStream\([\s\S]*?signal\?: AbortSignal,[\s\S]*?previousContent\?: string/)
  assert.match(apiSource, /stockAnalyzeStream[\s\S]*?signal,/)
  assert.match(storeSource, /AbortController/)
  assert.match(storeSource, /cancelAnalysis/)
  assert.match(dialogSource, /停止生成|中止生成/)
})

test('RPS 轮动分析支持取消并在卸载时中止请求', () => {
  const rpsSource = readFileSync(new URL('../src/components/RpsRotationDialog.tsx', import.meta.url), 'utf8')

  assert.match(apiSource, /rotationAnalyzeStream\([\s\S]*?signal\?: AbortSignal/)
  assert.match(apiSource, /rotationAnalyzeStream[\s\S]*?signal,/)
  assert.match(rpsSource, /AbortController/)
  assert.match(rpsSource, /中止分析|停止分析|中止生成/)
  assert.match(rpsSource, /正在启动轮动分析/)
  assert.doesNotMatch(rpsSource, /正在连接后端/)
  assert.match(rpsSource, /ev\.type === 'delta'[\s\S]*?setAnalysisStatus\(''\)/)
  assert.match(rpsSource, /ev\.type === 'done'[\s\S]*?setAnalysisStatus\(''\)/)
})
