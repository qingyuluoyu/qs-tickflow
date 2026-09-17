import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const apiSource = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
const pageSource = readFileSync(new URL('../src/pages/Financials.tsx', import.meta.url), 'utf8')

test('financial status type includes server-provided report freshness fields', () => {
  assert.match(apiSource, /latest_period_end\??:\s*string\s*\|\s*null/)
  assert.match(apiSource, /latest_announce_date\??:\s*string\s*\|\s*null/)
})

test('financial status cards show a report period and an explicit unsynced state', () => {
  assert.match(pageSource, /报告期/)
  assert.match(pageSource, /尚未同步/)
})
