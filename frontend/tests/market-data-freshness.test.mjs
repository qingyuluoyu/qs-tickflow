import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const read = (relative) => readFile(resolve(here, '..', relative), 'utf8')

const [dataPage, indicesPage, regimePage] = await Promise.all([
  read('src/pages/Data.tsx'),
  read('src/pages/Indices.tsx'),
  read('src/pages/Regime.tsx'),
])

assert.match(dataPage, /market_data_health/)
assert.match(dataPage, /unresolved/)
assert.match(dataPage, /provider_date/)
assert.match(indicesPage, /is_realtime/)
assert.match(indicesPage, /as_of/)
assert.match(indicesPage, /日线收盘/)
assert.match(regimePage, /useDataStatus/)
assert.match(regimePage, /计算滞后/)

console.log('market data freshness contract: PASS')
