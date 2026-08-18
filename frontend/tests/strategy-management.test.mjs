import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('策略页使用管理入口并提供删除与初始版本恢复契约', async () => {
  const [screener, dialog, api, storage, pool] = await Promise.all([
    readFile(new URL('../src/pages/Screener.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/screener/StrategyStoreDialog.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/storage.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/useStrategyPool.ts', import.meta.url), 'utf8'),
  ])

  assert.match(screener, /管理策略/)
  assert.doesNotMatch(screener, /获取策略/)
  assert.match(dialog, /strategyDelete/)
  assert.match(dialog, /回退初始版本/)
  assert.match(api, /strategyRestoreDefaults/)
  assert.match(api, /builtin_strategy_ids/)
  assert.match(storage, /strategyPool:.*kv<string\[\]>\(.*prefix/s)
  assert.match(pool, /userId/)
  assert.match(screener, /useStrategyPool\(user\.id\)/)
})
