import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const testDir = dirname(fileURLToPath(import.meta.url))
const layout = await readFile(resolve(testDir, '../src/components/Layout.tsx'), 'utf8')
const monitoring = await readFile(resolve(testDir, '../src/pages/settings/Monitoring.tsx'), 'utf8')
const menuSettings = await readFile(resolve(testDir, '../src/pages/settings/MenuSettings.tsx'), 'utf8')

const navBlock = layout.match(/const nav = \[([\s\S]*?)\] as const/)?.[1]
assert.ok(navBlock, '主导航定义应存在')

const indicesPosition = navBlock.indexOf("to: '/indices'")
const assetPosition = navBlock.indexOf("to: '/asset-allocation'")
const dataPosition = navBlock.indexOf("to: '/data'")

assert.ok(indicesPosition >= 0, '指数入口应保留')
assert.ok(assetPosition > indicesPosition, '资产配置应位于指数之后')
assert.ok(dataPosition > assetPosition, '资产配置应位于数据之前')
assert.match(navBlock.slice(assetPosition, assetPosition + 180), /label: '资产配置'/)
assert.doesNotMatch(navBlock.slice(assetPosition, assetPosition + 220), /external: true/)

assert.doesNotMatch(layout, /SidebarIndexQuotes|sidebarIndexQuotes|CORE_INDEXES/)
assert.doesNotMatch(monitoring, /SIDEBAR_INDEX_OPTIONS|sidebarIndexSymbols|indicesPinned|左侧菜单指数|指数卡片常驻显示/)
assert.match(menuSettings, /id: '\/asset-allocation', label: '资产配置'/)
assert.doesNotMatch(menuSettings, /id: '\/asset-allocation', label: '资产配置',[\s\S]{0,160}external: true/)

console.log('asset allocation navigation contract: PASS')
