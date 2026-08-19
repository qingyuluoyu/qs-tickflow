import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const html = await readFile(resolve(here, '..', 'public', 'asset-allocation.html'), 'utf8')

assert.doesNotMatch(html, /<header class="page-head">/, '章节入口上方不应再有独立页面头部')
assert.doesNotMatch(html, /WEALTH EDUCATION \/ STATIC PAGE/, '顶部品牌说明应移除')
assert.doesNotMatch(html, /id="view-index"/, '顶部章节计数卡应移除')
assert.doesNotMatch(html, /Stock Panel/, '资产子页面不应使用独立的 Stock Panel 品牌')
assert.doesNotMatch(html, /class="rail-card"/, '资产子页面不应添加主工作台没有的 Expert 卡片')
assert.match(html, /brand-wordmark\.png/, '资产子页面应复用主工作台品牌字标')
assert.match(
  html,
  /\.shell\{[^}]*grid-template-columns:14rem minmax\(0,1fr\);grid-template-rows:3\.25rem minmax\(0,1fr\)/,
  '资产页应使用原工作台的侧栏与顶栏基线',
)
assert.match(html, /\.sidebar\{grid-row:2\}/, '资产子页面侧栏应从主工作台顶栏下方开始')
assert.match(html, /\.topbar\{grid-column:2;grid-row:1\}/, '资产子页面顶栏应固定在右侧第一行')
assert.match(html, /\.main-pane\{grid-column:2;grid-row:2\}/, '资产子页面内容区应固定在右侧第二行')
assert.match(
  html,
  /@media \(min-width:1024px\)\{html\{font-size:clamp\(16px,calc\(13\.257px \+ 0\.2679vw\),18\.4px\)\}\}/,
  '资产页应复用原工作台的桌面端根字号缩放',
)
assert.equal((html.match(/data-page-tab=/g) ?? []).length, 4, '资产页应只保留四个章节入口')

console.log('asset-allocation layout contract: PASS')
