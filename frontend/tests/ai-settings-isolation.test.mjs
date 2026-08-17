import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/pages/settings/AI.tsx', import.meta.url), 'utf8')

test('AI 设置页区分平台默认与个人 API 覆盖', () => {
  assert.match(source, /ai_source/)
  assert.match(source, /配置个人 API/)
  assert.match(source, /恢复平台默认/)
})
