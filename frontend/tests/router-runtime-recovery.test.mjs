import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('..', import.meta.url)

test('开发启动强制重建 Vite 依赖图，路由拥有自己的恢复页面', async () => {
  const [packageJson, routerSource, fallbackSource] = await Promise.all([
    readFile(new URL('../package.json', import.meta.url), 'utf8'),
    readFile(new URL('../src/router.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/RouteErrorFallback.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(packageJson, /"dev"\s*:\s*"vite --force"/)
  assert.match(routerSource, /import \{ RouteErrorFallback \} from '\.\/components\/RouteErrorFallback'/)
  assert.match(routerSource, /errorElement:\s*<RouteErrorFallback\s*\/>/)
  assert.match(fallbackSource, /function RouteErrorFallback\(\)/)
  assert.match(fallbackSource, /window\.location\.reload\(\)/)
})
