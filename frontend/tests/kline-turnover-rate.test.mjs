import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const dailyChartSource = readFileSync(
  new URL('../src/components/StockDailyKChart.tsx', import.meta.url),
  'utf8',
)
const candlestickSource = readFileSync(
  new URL('../src/components/EChartsCandlestick.tsx', import.meta.url),
  'utf8',
)

test('daily K-line keeps point-in-time turnover and chart prefers it over latest shares', () => {
  assert.match(
    dailyChartSource,
    /turnover_rate:\s*r\.turnover_rate\s*!=\s*null\s*\?\s*Number\(r\.turnover_rate\)\s*:\s*null/,
    'toOHLC must preserve the turnover rate supplied for each trading date',
  )
  assert.match(
    candlestickSource,
    /turnover_rate\?:\s*number\s*\|\s*null/,
    'OHLC must carry the point-in-time turnover rate',
  )
  assert.match(
    candlestickSource,
    /d\.turnover_rate\s*!=\s*null\s*\?\s*d\.turnover_rate\s*:/,
    'the chart must prefer the row turnover rate before the latest-share fallback',
  )
})
