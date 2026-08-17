# 个股分析 K 线全屏实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为个股分析 K 线增加可退出的全屏查看，并确保底部时间滑块在全屏和尺寸切换后仍可用且保持用户选择的时间范围。

**Architecture:** 只改 `AnalysisKChart`，用浏览器 Fullscreen API 将包含关键价位开关、K 线、成交量和 ECharts `dataZoom` 的图表区域整体放大；不改变数据接口或其他页面图表。图表重新设置 option 时读取现有 dataZoom 范围，避免进入/退出全屏时重置时间窗口。

**Tech Stack:** React 18, TypeScript, ECharts 5, lucide-react, Vite。

## Global Constraints

- 保持现有 ECharts 图表数据、关键价位和时间滑块行为。
- 仅修改个股分析 K 线组件及其测试，不改后端数据接口。
- 全屏 API 不可用时提供同等的 fixed 覆盖层降级，并支持 Escape/关闭按钮退出。

---

### Task 1: 锁定全屏与时间范围保持契约

**Files:**
- Create: `frontend/scripts/test-analysis-kchart.mjs`

- [ ] **Step 1: Write the failing contract test**

```js
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
```

- [ ] **Step 2: Run the contract test and verify it fails**

Run: `node scripts/test-analysis-kchart.mjs`

Expected: FAIL because `AnalysisKChart.tsx` has no Fullscreen API or fullscreen labels yet.

### Task 2: Implement fullscreen chart shell and preserve dataZoom

**Files:**
- Modify: `frontend/src/components/stock-analysis/AnalysisKChart.tsx`

- [ ] **Step 1: Add fullscreen state, browser events, and fallback close behavior**

Add a ref for the chart shell, state for native/fallback fullscreen, viewport height tracking, and a `toggleFullscreen` handler that calls `requestFullscreen`/`exitFullscreen` when available and otherwise toggles a fixed overlay.

- [ ] **Step 2: Make the chart shell include controls, chart, and time slider**

Wrap the existing controls, ECharts canvas, and level overview in the fullscreen shell. Add an accessible expand/close button using `Maximize2` and `Minimize2`. Keep the existing ECharts slider in the same shell so it remains visible and draggable in fullscreen.

- [ ] **Step 3: Preserve the active ECharts dataZoom window**

Before `setOption(..., true)`, read the previous `dataZoom[0].start/end` and apply them to both the inside and slider zoom definitions. Use a viewport-derived height only while fullscreen and call `resize()` after updates.

### Task 3: Verify the feature

**Files:**
- Test: `frontend/scripts/test-analysis-kchart.mjs`

- [ ] **Step 1: Run the contract test**

Run: `node scripts/test-analysis-kchart.mjs`

Expected: PASS.

- [ ] **Step 2: Run frontend typecheck/build**

Run: `pnpm build`

Expected: TypeScript and Vite build exit 0.

- [ ] **Step 3: Manually verify in `/stock-analysis`**

Search/select a stock, drag the bottom time slider, click the fullscreen button, confirm the K-line, volume bars, and slider are all visible, confirm the selected range remains, then exit with the button and Escape.
