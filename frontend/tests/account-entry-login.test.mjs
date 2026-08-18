import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('账户入口提供登录、注册和切换账户路径', async () => {
  const [entrySource, layoutSource, authGateSource, queryKeysSource, storageSource] = await Promise.all([
    readFile(new URL('../src/components/AccountEntry.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/Layout.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/AuthGate.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/queryKeys.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/storage.ts', import.meta.url), 'utf8'),
  ])

  assert.match(entrySource, /mode.*login.*register|mode.*register.*login/s)
  assert.match(entrySource, /登录已有账户/)
  assert.match(entrySource, /注册新账户/)
  assert.match(entrySource, /authEntry\(/)
  assert.match(entrySource, /登录模式.*不要求姓名|登录时不要求姓名/s)
  assert.match(layoutSource, /切换账户/)
  assert.match(authGateSource, /setHasExistingAccounts\(status\.configured\)/)
  assert.match(authGateSource, /cancelQueries\(\)/)
  assert.match(authGateSource, /queryClient\.clear\(\)/)
  assert.match(queryKeysSource, /watchlistFor/)
  assert.match(storageSource, /storageForUser/)
})
