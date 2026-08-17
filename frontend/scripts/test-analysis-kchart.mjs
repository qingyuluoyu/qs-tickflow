import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/stock-analysis/AnalysisKChart.tsx', import.meta.url), 'utf8')
for (const required of [
  'requestFullscreen',
  'fullscreenchange',
  'dataZoom',
  '全屏',
  '退出全屏',
]) {
  if (!source.includes(required)) throw new Error(`missing K-chart fullscreen contract: ${required}`)
}

console.log('K-chart fullscreen contract passed')
