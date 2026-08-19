import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const tailwindConfig = readFileSync(new URL('../tailwind.config.ts', import.meta.url), 'utf8')
const themeCss = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')

test('橙黄琥珀 Tailwind 色板统一映射为天蓝色', () => {
  assert.match(tailwindConfig, /import colors from 'tailwindcss\/colors'/)
  for (const palette of ['orange', 'amber', 'yellow']) {
    assert.match(
      tailwindConfig,
      new RegExp(`\\b${palette}\\s*:\\s*colors\\.sky`),
      `${palette} 色板应映射为天蓝色`,
    )
  }
})

test('语义 warning 在亮暗主题中均使用天蓝色', () => {
  assert.equal((themeCss.match(/--warning:\s*199 89% 48%/g) ?? []).length, 2)
  assert.doesNotMatch(themeCss, /--warning:\s*32 95% 50%/)
})

function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return /\.(?:ts|tsx)$/.test(entry.name) ? [path] : []
  })
}

test('图表和标签不再绕过主题使用橙黄色十六进制色值', () => {
  const warmHex = /#(?:f59e0b|fbbf24|f97316|fb923c|facc15|eab308|fcd34d|fde047|fef08a)/i
  for (const file of sourceFiles(fileURLToPath(new URL('../src', import.meta.url)))) {
    assert.doesNotMatch(readFileSync(file, 'utf8'), warmHex, file)
  }
})
