import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const apiSource = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
const conceptSource = readFileSync(new URL('../src/pages/ConceptAnalysis.tsx', import.meta.url), 'utf8')
const industrySource = readFileSync(new URL('../src/pages/IndustryAnalysis.tsx', import.meta.url), 'utf8')
const ladderSource = readFileSync(new URL('../src/pages/LimitUpLadder.tsx', import.meta.url), 'utf8')

test('扩展数据契约携带可判断过期状态的元数据', () => {
  assert.match(apiSource, /interface ExtDataRowsResult[\s\S]*?data_freshness\?\:/)
  assert.match(apiSource, /data_freshness\?:[\s\S]*?is_stale\?: boolean/)
})

test('概念、行业和连板页面都展示统一的数据过期提示', () => {
  assert.match(conceptSource, /DataFreshnessNotice/)
  assert.match(conceptSource, /snapshotDate=\{rowsQuery\.data\?\.date\}/)
  assert.match(industrySource, /DataFreshnessNotice/)
  assert.match(industrySource, /snapshotDate=\{rowsQuery\.data\?\.date\}/)
  assert.match(ladderSource, /DataFreshnessNotice/)
})

test('新鲜度提示对旧快照采用前端日期兜底，不被错误的 false 标记隐藏', () => {
  const noticeSource = readFileSync(new URL('../src/components/DataFreshnessNotice.tsx', import.meta.url), 'utf8')
  assert.match(noticeSource, /staleByDate/)
  assert.match(noticeSource, /Boolean\(freshness\?\.is_stale\)/)
  assert.ok(noticeSource.includes('latestWeekday(beijingToday())'))
})
