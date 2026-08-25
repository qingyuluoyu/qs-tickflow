import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('个股与财务重新分析会把上一轮回答作为追问上下文', async () => {
  const [apiSource, stockStore, financialStore, stockDialog, financialDialog] = await Promise.all([
    readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/stockAnalysisStore.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/aiReportStore.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/stock-analysis/StockAnalysisDialog.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/financials/AiAnalysisDialog.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(apiSource, /previous_content:\s*previousContent/)
  assert.match(stockStore, /stockAnalyzeStream\(symbol, focus, controller\.signal, previousContent/)
  assert.match(financialStore, /financialAnalyzeStream\(symbol, focus, previousContent/)
  for (const dialogSource of [stockDialog, financialDialog]) {
    assert.match(dialogSource, /const previousContent = nextFocus && nextFocus !== originalFocus \? content : ''/)
    assert.match(dialogSource, /startAnalysis\(task\.symbol, name, nextFocus, previousContent\)/)
    assert.match(dialogSource, /继续追问/)
  }
})

test('复盘页的新关注点会携带当前报告继续追问', async () => {
  const [apiSource, reviewStore, reviewPage] = await Promise.all([
    readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/lib/reviewStore.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/Review.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(apiSource, /reviewStream\(asOf\?: string, focus\?: string, sections\?: string\[\], previousContent = ''\)/)
  assert.match(apiSource, /previous_content:\s*previousContent/)
  assert.match(reviewStore, /api\.reviewStream\(asOf, focus, sections, previousContent\)/)
  assert.match(reviewPage, /const previousContent = nextFocus && nextFocus !== originalFocus \? displayContent : ''/)
  assert.match(reviewPage, /startReviewGeneration\([\s\S]*sections, previousContent\)/)
  assert.match(reviewPage, /继续追问/)
})
