import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const apiSource = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
const pageSource = readFileSync(new URL('../src/pages/backtest/StrategyBacktest.tsx', import.meta.url), 'utf8')

test('strategy backtest API type exposes optional data quality metadata', () => {
  assert.match(apiSource, /data_quality\?:\s*StrategyBacktestDataQuality/)
  assert.match(apiSource, /symbols_loaded:\s*number/)
})

test('strategy backtest keeps an error path distinct from verified no-signal results', () => {
  assert.match(pageSource, /result\?\.error/)
  assert.match(pageSource, /本次条件下没有入场信号；数据覆盖已校验/)
  assert.match(pageSource, /dataQuality/)
})
