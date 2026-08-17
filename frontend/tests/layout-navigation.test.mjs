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
