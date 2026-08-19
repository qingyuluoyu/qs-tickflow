import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const publicRoot = resolve(here, '..', 'public')

const [main, allocationGame, townGame] = await Promise.all([
  readFile(resolve(publicRoot, 'asset-allocation.html'), 'utf8'),
  readFile(resolve(publicRoot, 'games', 'asset-allocation-game.html'), 'utf8'),
  readFile(resolve(publicRoot, 'games', 'milk-cola-town.html'), 'utf8'),
])

assert.match(main, /4321 法则/)
assert.match(main, /美林周期/)
assert.match(main, /财商训练/)
assert.match(main, /财商教育/)
assert.match(main, /配置总览/)
assert.equal((main.match(/data-page-tab=/g) ?? []).length, 4)
assert.equal((main.match(/data-view=/g) ?? []).length, 4)
assert.match(main, /--base:\s*#F6F7FB/)
assert.match(main, /color-scheme:\s*light/)
assert.match(main, /body\{font-size:13px\}/)
assert.match(main, /\.section-copy\{[^}]*font-size:13px/)
assert.match(main, /\.panel-header\{[^}]*height:46px/)
assert.match(main, /\.overview-hero::before/)
assert.match(main, /height:\s*100dvh/)
assert.match(main, /overflow:\s*hidden/)
assert.match(main, /id="rule-diagram"/)
assert.match(main, /id="merrill-matrix"/)
assert.match(main, /id="learning-loop"/)
assert.match(main, /id="allocation-flow"/)
assert.match(main, /id="decision-trace"/)
assert.match(main, /id="learning-signal"/)
assert.match(main, /id="allocation-chart"/)
assert.match(main, /id="cashflow-chart"/)
assert.equal((main.match(/<iframe\b/g) ?? []).length, 2)
assert.match(main, /data-game-tab="allocation"/)
assert.match(main, /data-game-tab="town"/)
assert.match(main, /games\/asset-allocation-game\.html/)
assert.match(main, /games\/milk-cola-town\.html/)
assert.match(main, /allowfullscreen/)
assert.match(main, /allow="fullscreen"/)
assert.match(main, /data-fullscreen/)
assert.match(main, /is-fullscreen/)
assert.match(main, /data-exit-fullscreen/)

for (const html of [main, allocationGame, townGame]) {
  for (const forbidden of ['股票', '个股', '证券', 'A股', '美股', '港股']) {
    assert.doesNotMatch(html, new RegExp(forbidden))
  }
}

console.log('asset-allocation static contract: PASS')
