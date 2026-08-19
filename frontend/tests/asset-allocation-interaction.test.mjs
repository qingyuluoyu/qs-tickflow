import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const html = await readFile(resolve(here, '..', 'public', 'asset-allocation.html'), 'utf8')

assert.match(html, /data-fullscreen="active"[^>]*aria-pressed="false"/)
assert.match(html, /退出全屏/)
assert.match(html, /fullscreenButton(?:\?\.|\.)setAttribute\('aria-pressed'/)
assert.doesNotMatch(html, /stopImmediatePropagation\(\)/)
assert.equal((html.match(/role="tabpanel" aria-labelledby="page-tab-/g) ?? []).length, 4)

console.log('asset-allocation interaction contract: PASS')
