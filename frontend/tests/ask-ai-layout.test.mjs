import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/ask-ai/AskAiDialog.tsx', import.meta.url), 'utf8')

test('问 AI 面板在视口内扩大约 30%', () => {
  assert.match(source, /w-\[min\(500px,calc\(100vw-2rem\)\)\]/)
  assert.match(source, /h-\[min\(680px,calc\(100vh-5rem\)\)\]/)
})
