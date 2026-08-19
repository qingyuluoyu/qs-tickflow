# 资产配置财商教育页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改主应用路由的前提下，新增一个可独立打开的桌面端静态“资产配置”教学页，左侧讲解 4321 法则、美林周期和财商训练，右侧通过两个 Tab 切换两个本地小游戏 iframe。

**Architecture:** 使用 Vite `public/` 下的独立 HTML，避免把未完成页面暴露到现有 React 主应用。主页只管理本地 Tab、概念卡片展开和静态教学状态；两个小游戏复制到 `public/games/` 作为 iframe 页面，并在复制过程中清除股票相关文案，保留原有互动玩法的结构和亮色视觉气质。

**Tech Stack:** 原生 HTML、CSS、JavaScript；复用仓库亮色设计语言中的 `#FAFAFA/#FFFFFF/#3B82F6/#8B5CF6/#F59E0B/#38BDF8`；Node.js 静态契约测试；Vite 静态资源构建。

## Global Constraints

- 页面面向已有一定资产、希望建立配置框架的用户，教学优先，不提供个股或交易建议。
- 页面中及两个 iframe 副本中不得出现股票相关内容、股票代码或个股管理入口。
- 4321 法则、美林周期、财商训练是左侧三张核心概念卡；右侧为双 Tab 财商小游戏区。
- 两个小游戏必须保留为可互动的静态 HTML，并通过 iframe 页面内嵌；不增加后端或真实数据请求。
- 不新增主应用路由，不修改 `frontend/src/router.tsx`、现有 React 页面或主文件。
- 交互必须是确定性的本地状态，清晰标注教育用途，不把静态演示包装成真实金融计算或投资建议。

---

### Task 1: Define the standalone page contract

**Files:**
- Create: `frontend/tests/asset-allocation-page.test.mjs`
- Test: `frontend/tests/asset-allocation-page.test.mjs`

**Interfaces:**
- Consumes: `frontend/public/asset-allocation.html` and its two `frontend/public/games/*.html` outputs.
- Produces: a zero-dependency Node test that verifies required page labels, two iframe sources, local tab hooks, and the forbidden stock vocabulary boundary.

- [x] **Step 1: Write the failing test**

  The test must read the three expected public files and assert:

  ```js
  assert.match(main, /4321 法则/)
  assert.match(main, /美林周期/)
  assert.match(main, /财商训练/)
  assert.equal((main.match(/<iframe\b/g) ?? []).length, 2)
  assert.match(main, /data-game-tab="allocation"/)
  assert.match(main, /data-game-tab="town"/)
  for (const html of [main, allocationGame, townGame]) {
    for (const forbidden of ['股票', '个股', '证券', 'A股', '美股', '港股']) {
      assert.doesNotMatch(html, new RegExp(forbidden))
    }
  }
  ```

- [x] **Step 2: Run the test and verify it fails because the page is missing**

  Run: `node frontend/tests/asset-allocation-page.test.mjs`

  Expected: FAIL with an `ENOENT` or missing-file assertion, not a syntax error.

- [x] **Step 3: Keep the test as the static contract**

  The test must not launch a server or mock browser APIs; it validates the exact files that Vite will publish.

---

### Task 2: Build the standalone education shell

**Files:**
- Create: `frontend/public/asset-allocation.html`

**Interfaces:**
- Consumes: two sibling iframe files at `games/asset-allocation-game.html` and `games/milk-cola-town.html`.
- Produces: a self-contained desktop-first page with a top brand strip, education introduction, three expandable concept cards, and a right-side two-tab iframe stage.

- [x] **Step 1: Add semantic page structure**

  Include a `main` landmark with a page header, an explanatory paragraph defining 财商教育, a three-card concept column, a game panel, two tab buttons with `aria-selected`, and two iframes with `title`, local relative `src` values, and `sandbox="allow-scripts"`.

- [x] **Step 2: Add the visual system**

  Use the source page’s light neutral background, white surfaces, thin zinc borders, blue/purple/orange/cyan accents, compact mono numerals, 14–16px body copy, restrained rounded cards, and subtle radial background glows. Keep the layout optimized for a 1440px desktop viewport and allow narrow-window scrolling without breaking the iframe.

- [x] **Step 3: Add deterministic interactions**

  Implement in-page JavaScript for:

  - clicking a concept card to expand one explanation at a time;
  - switching the active game Tab and iframe visibility;
  - updating the small “当前学习模块” label;
  - supporting keyboard activation through real buttons;
  - using the more restrictive `sandbox="allow-scripts"` on each local iframe.

- [x] **Step 4: Add educational boundaries**

  State that the page is for概念学习 and scenario practice, not a product recommendation or personalized investment advice. Do not include real market numbers, asset codes, or any stock-related wording.

---

### Task 3: Prepare the two static game documents

**Files:**
- Create: `frontend/public/games/asset-allocation-game.html`
- Create: `frontend/public/games/milk-cola-town.html`

**Interfaces:**
- Consumes: the three user-provided HTML references outside the repository.
- Produces: two local iframe-compatible, script-enabled static games with no network dependency and no forbidden stock vocabulary.

- [x] **Step 1: Copy the two user-selected games into the public asset boundary**

  Use the user-provided `资产配置大师.html` as the allocation game base and `牛奶可乐小镇.html` as the financial-literacy game base. Do not modify the original files outside the repository.

- [x] **Step 2: Remove forbidden stock vocabulary from the copies**

  Replace stock-specific category names, examples, questions, and recap copy with neutral “增长类资产 / 长期增值 / 分散配置” language. Replace the single stock example in 牛奶可乐小镇 with a generic sunk-cost example. Preserve the games’ buttons, scoring, lesson flow, and responsive behavior.

- [x] **Step 3: Validate iframe safety and local operation**

  Ensure the copies do not load remote scripts, do not depend on a backend, and retain the original local event handlers after text sanitization.

---

### Task 4: Verify the slice

**Files:**
- Modify only files created by Tasks 1–3 if verification finds a defect.

- [x] **Step 1: Run the static contract test**

  Run: `node frontend/tests/asset-allocation-page.test.mjs`

- [x] **Step 2: Run the frontend build**

  Run: `pnpm --dir frontend build`

- [x] **Step 3: Check the diff and forbidden terms**

  Run: `git diff --check`

  Run: `rg -n "股票|个股|证券|A股|美股|港股" frontend/public/asset-allocation.html frontend/public/games`

  Expected: no matches in published page/game files or the static contract test.

- [x] **Step 4: Manually verify the page at the Vite static URL**

  Open `/asset-allocation.html` at the local Vite host and check the default concept expansion, each concept toggle, both game Tabs, iframe interaction, keyboard focus, and a 1440px desktop layout. Report any unverified browser-only behavior separately.
