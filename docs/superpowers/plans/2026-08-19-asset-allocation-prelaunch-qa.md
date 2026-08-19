# Asset Allocation Pre-Launch QA and UX Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在资产配置子页面上线前，系统性发现并处理影响用户理解、交互完成、固定视口布局、iframe 游戏和 React 集成的体验问题。

**Architecture:** 保持现有 React Layout → `AssetAllocation` 页面 → `/asset-allocation.html?embed=1` iframe 的边界，不引入后端或新依赖。静态教学内容与 iframe 内游戏继续由页面自包含，发现的缺陷以静态契约测试、浏览器冒烟和最小 UI 修复闭环处理。

**Tech Stack:** React + TypeScript、Vite、单页静态 HTML/CSS/JavaScript、Node 静态契约测试、Playwright-compatible in-app browser。

## Global Constraints

- 保持资产配置为 React 主布局中的子页面，不恢复独立重复侧栏或顶部壳层。
- 保持 01–04 四个页面标题、亮色默认主题、桌面端固定比例与 iframe 游戏入口。
- 页面内不出现股票管理相关内容；静态页面与两个游戏继续通过现有禁用词契约。
- 不改变金融计算、演示比例的教学口径；示例数字继续显式标记为示意结构。
- 不新增后端接口、数据库迁移或运行时外部数据依赖。
- 每个确认的行为缺陷必须先有能在旧实现失败的回归测试，再写生产代码修复。

---

### Task 1: 建立代码与运行基线

**Files:**
- Read: `CONTRIBUTING.md`
- Read: `frontend/src/router.tsx`
- Read: `frontend/src/pages/AssetAllocation.tsx`
- Read: `frontend/public/asset-allocation.html`
- Read: `frontend/public/games/asset-allocation-game.html`
- Read: `frontend/public/games/milk-cola-town.html`
- Read: `frontend/tests/asset-allocation-page.test.mjs`
- Read: `frontend/tests/asset-allocation-layout.test.mjs`
- Read: `frontend/tests/asset-allocation-nav.test.mjs`
- Read: `frontend/tests/asset-allocation-react-route.test.mjs`

**Interfaces:**
- Consumes: 当前 React 路由、静态页面契约、iframe URL、页面 Tab 与游戏 Tab 标记。
- Produces: 可复现的文件边界、运行端口、测试命令和上线前检查矩阵。

- [ ] **Step 1: 检查工作区状态与运行进程**

```powershell
git status --short
Get-Process node,python -ErrorAction SilentlyContinue | Select-Object ProcessName,Id
```

Expected: 不覆盖既有修改；确认前端 3012、后端 3018 是否仍在运行。

- [ ] **Step 2: 运行当前静态契约**

```powershell
node frontend/tests/asset-allocation-layout.test.mjs
node frontend/tests/asset-allocation-page.test.mjs
node frontend/tests/asset-allocation-nav.test.mjs
node frontend/tests/asset-allocation-react-route.test.mjs
```

Expected: 四项均通过；若失败，先记录根因，不在审计阶段绕过断言。

---

### Task 2: 捕获上线前 UX 与可访问性证据

**Files:**
- Create: `artifacts/asset-allocation-qa/01-overview.png`
- Create: `artifacts/asset-allocation-qa/02-rule-4321.png`
- Create: `artifacts/asset-allocation-qa/03-merrill-cycle.png`
- Create: `artifacts/asset-allocation-qa/04-training-game.png`
- Create: `artifacts/asset-allocation-qa/05-narrow-window.png`
- Inspect: `frontend/public/asset-allocation.html`

**Interfaces:**
- Consumes: `http://localhost:3012/asset-allocation`、当前 in-app browser、iframe 页面 Tab。
- Produces: 每个关键状态的截图、DOM 状态和问题清单；只记录截图真实可见的问题，不把未检查范围写成已通过。

- [ ] **Step 1: 检查桌面默认态**

确认 React 外层只出现一个侧栏和一个顶部用户区，资产页面默认显示 01，iframe 充满内容区且没有页面级滚动条。

- [ ] **Step 2: 逐页检查四个 Tab**

依次点击 `01 配置总览`、`02 4321 法则`、`03 美林周期`、`04 财商训练`，每次检查选中态、标题、内容是否被裁切、说明文字是否可读、右侧卡片是否重叠。

- [ ] **Step 3: 检查游戏交互**

在 `04 财商训练` 中切换两个游戏，检查 iframe 是否加载、游戏 Tab 是否同步、内部滚动是否可用、全屏按钮是否存在且能退出全屏；刷新后不应出现空白或错误页。

- [ ] **Step 4: 检查键盘与窄窗口**

使用 Tab 键经过页面 Tab、游戏 Tab、全屏按钮和游戏 iframe，确认焦点可见；在 1024×720 与 1280×720 检查布局，记录文字截断、遮挡、意外双滚动和无法操作的控件。

- [ ] **Step 5: 形成问题分级**

`P0/P1` 阻断上线：页面不可访问、核心 Tab/游戏不可用、错误内容或严重遮挡；`P2` 必须修复：明显交互错误、固定布局破坏、焦点不可达、刷新状态异常；`P3` 记录：局部间距、文案和视觉 polish。

---

### Task 3: 为已确认问题补充失败回归测试

**Files:**
- Modify: `frontend/tests/asset-allocation-page.test.mjs`
- Modify: `frontend/tests/asset-allocation-react-route.test.mjs`
- Create or modify: `frontend/tests/asset-allocation-interaction.test.mjs` only when a DOM-level regression is confirmed

**Interfaces:**
- Consumes: Task 2 中复现的具体行为和选择器。
- Produces: 可在修复前失败、修复后通过的最小回归断言。

- [ ] **Step 1: 先写单一失败断言**

每个问题只增加一条明确行为断言，例如页面必须存在 `aria-selected` 的页面 Tab、iframe 必须包含 `allowfullscreen`、游戏切换必须只保留一个可见 iframe、嵌入态必须隐藏独立壳层。

- [ ] **Step 2: 运行新增测试确认红灯**

```powershell
node frontend/tests/asset-allocation-interaction.test.mjs
```

Expected: 失败原因对应已复现的缺陷，而不是测试脚本本身语法错误。

---

### Task 4: 实施最小体验修复

**Files:**
- Modify: `frontend/public/asset-allocation.html`
- Modify: `frontend/src/pages/AssetAllocation.tsx` only if the React loading/error boundary is proven to be the source of a defect
- Modify: corresponding test file from Task 3

**Interfaces:**
- Consumes: 已确认的失败回归测试和既有 CSS/JS 状态逻辑。
- Produces: 不改变页面信息架构的体验修复；保留 iframe 全屏、页面 Tab 与游戏 Tab 的现有契约。

- [ ] **Step 1: 修复最高级别问题**

一次只改一个根因，避免用强制刷新、吞异常或额外延时掩盖问题。

- [ ] **Step 2: 立即运行对应回归测试**

```powershell
node frontend/tests/asset-allocation-interaction.test.mjs
```

Expected: 新增断言从红灯变绿灯，且没有改变既有四项静态契约。

- [ ] **Step 3: 复查风险边界**

确认修改没有引入禁止内容、没有让页面级滚动恢复、没有破坏 iframe `allowfullscreen`、没有改变演示比例或 React 路由兼容别名。

---

### Task 5: 上线前完整回归与人工验收

**Files:**
- Read: `frontend/public/asset-allocation.html`
- Read: `frontend/src/pages/AssetAllocation.tsx`
- Read: final `git diff` and `git status`

**Interfaces:**
- Consumes: 所有修复后的代码、回归测试、浏览器审计证据。
- Produces: 可上线/修改后上线/阻断上线结论，包含实际命令、失败项、剩余风险和人工验收步骤。

- [ ] **Step 1: 运行前端质量门禁**

```powershell
pnpm --dir frontend build
pnpm --dir frontend lint
git diff --check
```

Expected: build 退出码 0；lint 无 error；历史 warning 单独列出；diff check 无空白错误。

- [ ] **Step 2: 运行所有资产配置静态与交互测试**

```powershell
node frontend/tests/asset-allocation-layout.test.mjs
node frontend/tests/asset-allocation-page.test.mjs
node frontend/tests/asset-allocation-nav.test.mjs
node frontend/tests/asset-allocation-react-route.test.mjs
node frontend/tests/asset-allocation-interaction.test.mjs
```

- [ ] **Step 3: 做浏览器冒烟复核**

重新验证默认态、四个 Tab、两个游戏、全屏、刷新、直达 `/asset-allocation` 和窄窗口；将实际未覆盖的浏览器能力标记为剩余风险。

- [ ] **Step 4: 输出上线结论**

按 P0–P3 排序报告问题；只有核心流程、固定布局、页面切换、游戏加载和错误/刷新路径都有证据时，才标记本轮“已实现并验证”。
