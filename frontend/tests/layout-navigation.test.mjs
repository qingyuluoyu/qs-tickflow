import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const layoutSource = readFileSync(new URL('../src/components/Layout.tsx', import.meta.url), 'utf8')

test('市场环境导航不展示 Beta 标识', () => {
  const regimeNav = layoutSource
    .split(/\r?\n/)
    .find((line) => line.includes("to: '/regime'"))

  assert.ok(regimeNav, '应保留市场环境导航入口')
  assert.doesNotMatch(regimeNav, /\bbadge\s*:/, '市场环境导航不应带有状态标识')
})

test('左侧导航使用设计稿对应的彩色图标配置', () => {
  assert.match(layoutSource, /Grid2X2/)
  assert.match(layoutSource, /Crosshair/)
  assert.match(layoutSource, /ChartNoAxesColumnIncreasing/)
  assert.match(layoutSource, /tone:\s*'orange'/)
  assert.match(layoutSource, /rounded-xl/)
})

test('侧栏支持收起展开并将状态持久化', () => {
  assert.match(layoutSource, /sidebarCollapsed/)
  assert.match(layoutSource, /sidebar-collapsed/)
  assert.match(layoutSource, /收起侧栏/)
  assert.match(layoutSource, /展开侧栏/)
})

test('布局使用 Mantine AppShell 且用户胶囊固定在 Header', () => {
  assert.match(layoutSource, /<AppShell/)
  assert.match(layoutSource, /AppShell\.Header/)
  assert.match(layoutSource, /AppShell\.Navbar/)
  assert.match(layoutSource, /AppShell\.Main/)
  // 用户胶囊不再以 sticky 悬浮方式遮挡页面内容
  assert.doesNotMatch(layoutSource, /pointer-events-none sticky/)
})

test('移动端通过 Burger 打开抽屉式导航', () => {
  assert.match(layoutSource, /<Burger/)
  assert.match(layoutSource, /breakpoint:\s*'lg'/)
  assert.match(layoutSource, /collapsed:\s*\{\s*mobile:\s*!mobileOpened/)
})

test('看板侧栏指数定期刷新预加载快照', () => {
  assert.match(
    layoutSource,
    /queryKey:\s*\[\.\.\.QK\.indexQuotes, 'sidebar',[\s\S]*?refetchInterval:\s*location\.pathname === '\/' \? 30_000 : false/,
    '看板主快照切换数据源后，侧栏指数不能永久保留旧的 React Query 缓存',
  )
})
