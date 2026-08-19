import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('策略构建器提供历史窗口后端和 filter_history 模板', async () => {
  const source = await readFile(new URL('../src/components/screener/StrategyBuilderDialog.tsx', import.meta.url), 'utf8')

  assert.match(source, /python_history_legacy/)
  assert.match(source, /历史策略/)
  assert.match(source, /filter_history\s*\(/)
  assert.match(source, /LOOKBACK_DAYS/)
})
