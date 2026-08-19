# 资产配置工作台式子页重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将独立资产配置页改造成符合 TickFlow 当前亮色默认 UI 的固定视口教学子页，提供四个留白更充足、内容可执行的内部视图，不产生页面纵向滚动。

**Architecture:** 继续使用 `frontend/public/asset-allocation.html` 作为不接入主路由的独立静态页，但重建为 AppShell 风格：左侧窄导航、顶栏、固定内容区和四个内部 view。四个 view 通过本地按钮切换，配置图表用静态 HTML/CSS 数据可视化表达；财商训练 view 内保留两个本地小游戏 iframe Tab，并提供页面内沉浸式全屏兜底。

**Tech Stack:** 原生 HTML/CSS/JavaScript、TickFlow 现有深色 token、现有两个静态小游戏副本、Node 静态契约测试、Vite。

## Global Constraints

- 页面固定为桌面端工作台比例：`html, body { height: 100%; overflow: hidden; }`，主内容不允许页面级纵向滚动。
- 四个内部标题固定为：配置总览、4321 法则、美林周期、财商训练。
- 每个 view 都必须有成组的概念说明、结构化信息和至少一个演示图或信息图。
- 仅使用当前 TickFlow 的亮色默认背景、细边框、蓝紫橙青强调色、克制卡片和等宽数字风格。
- 财商训练 view 继续嵌入两个本地小游戏 iframe；不接后端、不接实时数据、不出现股票相关内容。
- 配置总览至少提供资金任务比例图和期限带图；游戏 Tab 必须能够触发全屏或页面内沉浸式全屏。
- 不修改 `frontend/src/router.tsx` 或主应用页面。

---

### Task 1: Extend the static contract first

**Files:**
- Modify: `frontend/tests/asset-allocation-page.test.mjs`

- [x] Add assertions for four `data-page-tab` controls, four `data-view` panels, dark token `#0A0A0B`, fixed `100dvh`/`overflow:hidden`, and diagram IDs `rule-diagram`, `merrill-matrix`, `learning-loop`.
- [x] Run `node frontend/tests/asset-allocation-page.test.mjs` and confirm the current light prototype fails on the missing four-view contract.

---

### Task 2: Rebuild the fixed TickFlow workbench shell

**Files:**
- Modify: `frontend/public/asset-allocation.html`

- [x] Add a 236px sidebar with TickFlow branding, familiar project navigation labels, active `资产配置` item, and a 52px top bar with breadcrumb/status.
- [x] Add four page tabs using `data-page-tab="overview|rule|cycle|training"` and four `data-view` panels; only one view is visible at a time.
- [x] Use `height:100dvh`, `overflow:hidden`, `min-height:0`, and fixed grid/flex children so the viewport does not scroll vertically.
- [x] Keep all content in the viewport through compact grid rows, not page-level overflow.

---

### Task 3: Add the four dense teaching views and diagrams

**Files:**
- Modify: `frontend/public/asset-allocation.html`

- [x] `配置总览`: explain target, term, liquidity, risk, cash-flow role, and decision order; add a “一笔钱 → 四个任务” allocation map.
- [x] `4321 法则`: add 40/30/20/10 stacked allocation diagram, four bucket definitions, sample `100 万` split, and boundary notes explaining it is a heuristic rather than a fixed answer.
- [x] `美林周期`: add a growth/inflation quadrant matrix with four phases, phase transition sequence, and a four-row explanation table covering what each phase is trying to protect.
- [x] `财商训练`: add definitions for opportunity cost, compounding, liquidity, risk capacity, diversification, and a `理解 → 选择 → 反馈 → 复盘` loop; embed the two games using the existing iframe Tab interaction.

---

### Task 4: Verify the fixed viewport and interactions

**Files:**
- Modify only files above if verification finds a defect.

- [x] Run `node frontend/tests/asset-allocation-page.test.mjs`.
- [x] Run `pnpm --dir frontend build`.
- [x] Run `git diff --check` and scan `frontend/public/asset-allocation.html frontend/public/games` for forbidden stock terms and remote dependencies.
- [x] In the local browser, test all four view buttons, verify `document.documentElement.scrollHeight === window.innerHeight` at the default desktop viewport, inspect each diagram, switch both game tabs, and enter one game round.
