import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('Vite 在内置中间件前拒绝 malformed URI，避免开发页被 overlay 卡死', async () => {
  const [tsConfig, jsConfig] = await Promise.all([
    readFile(new URL('../vite.config.ts', import.meta.url), 'utf8'),
    readFile(new URL('../vite.config.js', import.meta.url), 'utf8'),
  ])

  for (const source of [tsConfig, jsConfig]) {
    assert.match(source, /configureServer\s*\(/)
    assert.match(source, /decodeURI\(req\.url/)
    assert.match(source, /statusCode\s*=\s*400/)
  }
})

test('流式响应坏行和无 done 都进入可见错误态', async () => {
  const [apiSource, storeSource, debateSource, rpsSource] = await Promise.all([
    readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/stockAnalysisStore.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/stock-analysis/DebateDialog.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/RpsRotationDialog.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(apiSource, /readNdjsonStream/)
  assert.match(apiSource, /流式响应格式异常/)
  assert.match(storeSource, /sawDone/)
  assert.match(debateSource, /sawDone/)
  assert.match(rpsSource, /sawDone/)
})
