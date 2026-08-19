import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const [router, page, html, navRoutes, layout, menuSettings] = await Promise.all([
  readFile(resolve(here, '..', 'src', 'router.tsx'), 'utf8'),
  readFile(resolve(here, '..', 'src', 'pages', 'AssetAllocation.tsx'), 'utf8').catch(() => ''),
  readFile(resolve(here, '..', 'public', 'asset-allocation.html'), 'utf8'),
  readFile(resolve(here, '..', 'src', 'lib', 'navRoutes.ts'), 'utf8').catch(() => ''),
  readFile(resolve(here, '..', 'src', 'components', 'Layout.tsx'), 'utf8'),
  readFile(resolve(here, '..', 'src', 'pages', 'settings', 'MenuSettings.tsx'), 'utf8'),
])

assert.match(router, /const AssetAllocation = lazyRoute\(/, '资产配置应注册为 React 页面')
assert.match(router, /path: 'asset-allocation', element: <AssetAllocation \/>/, '资产配置应挂在 Layout 内部路由')
assert.match(page, /asset-allocation\.html\?embed=1/, 'React 页面应复用现有静态教学内容区')
assert.match(page, /title="资产配置教学"/, '嵌入内容需要有可访问标题')
assert.match(html, /classList\.add\('embed'\)/, '静态资产页应支持 React 内嵌模式')
assert.match(html, /body\.embed \.sidebar, body\.embed \.topbar/, '内嵌模式不应重复渲染主布局外壳')
assert.match(navRoutes, /asset-allocation\.html.*asset-allocation/, '旧静态入口需要映射到 React 路由')
assert.match(layout, /canonicalNavRoute/, '主布局应兼容旧菜单路径')
assert.match(menuSettings, /canonicalNavRoute/, '菜单设置应兼容旧菜单路径')

console.log('asset-allocation React route contract: PASS')
