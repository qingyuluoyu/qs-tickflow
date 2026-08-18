import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('AI 对话分离思考过程并默认只展示回答', async () => {
  const [api, reviewStore, stockStore, stockDialog, reviewPage] = await Promise.all([
    readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/reviewStore.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/stockAnalysisStore.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/stock-analysis/StockAnalysisDialog.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/Review.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(api, /reasoning_delta/)
  assert.match(api, /truncated\?: boolean/)
  assert.match(api, /buf \+= decoder\.decode\(\)/)
  assert.match(reviewStore, /reasoning: string/)
  assert.match(reviewStore, /reasoning_delta/)
  assert.match(stockStore, /reasoning: string/)
  assert.match(stockStore, /continuation/)
  assert.match(stockDialog, /思考过程（模型草稿）/)
  assert.match(stockDialog, /reasoningOpen.*false|useState\(false\)/s)
  assert.match(stockDialog, /MarkdownRenderer content=\{content\}/)
  assert.match(reviewPage, /思考过程（模型草稿）/)
  assert.match(reviewPage, /truncated/)
})
