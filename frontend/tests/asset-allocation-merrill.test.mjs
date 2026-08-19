import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const html = await readFile(resolve(here, '..', 'public', 'asset-allocation.html'), 'utf8')

assert.match(html, /data-merrill-grid/)
assert.equal((html.match(/data-merrill-phase=/g) ?? []).length, 4)
assert.match(html, /data-phase-detail/)
assert.equal((html.match(/data-merrill-reading=/g) ?? []).length, 3)
assert.equal((html.match(/data-merrill-practice=/g) ?? []).length, 4)
assert.match(html, /把周期判断变成组合动作/)
assert.match(html, /周期边界/)

console.log('asset-allocation Merrill Cycle content contract: PASS')
