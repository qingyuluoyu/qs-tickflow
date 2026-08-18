# Strategy Management and Initial Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the placeholder “获取策略” entry with a real “管理策略” surface, allow users to delete their own custom/AI/composite strategies, and provide a confirmed action that restores the strategy layer to the packaged 18 built-in strategies.

**Architecture:** Keep the existing `StrategyEngine` registry and per-user workspace boundaries. Add one authenticated strategy-management API that deletes only files under the current user’s strategy directories and clears strategy overrides. The frontend management dialog will call that API, refresh the registry, remove deleted IDs from the local strategy pool, and replace the pool with the returned built-in ID order after a restore.

**Tech Stack:** FastAPI/Pydantic, existing `StrategyEngine` and per-user `request_data_root`, React/TypeScript, React Query, existing motion/icon/modal styling, pytest and TypeScript/Vite verification.

## Global Constraints

- Built-in strategy source files under `backend/app/strategy/builtin/` are never writable or deletable through this feature.
- A delete request can target only `custom`, `ai`, or `composite` strategies belonging to the current user workspace.
- Restore requires explicit confirmation, removes only user strategy files and strategy override JSON files, and must not touch watchlists, market data, accounts, or other user data.
- Existing delete behavior and strategy-settings flows remain compatible.
- No production code is changed before a failing regression test demonstrates the missing restore contract.

## Work Packages

### 1. Establish the strategy-management contract

- Inspect the current strategy route, runtime registry, per-user data root, and frontend strategy dialogs.
- Define the restore request/response contract (`confirm`, deleted IDs, built-in IDs, count) and failure behavior for unsafe paths or write failures.
- Add backend tests for confirmation, complete removal of user strategy files/overrides, retention of exactly 18 built-ins, and per-user path safety.

### 2. Implement safe backend restore behavior

- Add a restore-defaults route using the existing request-scoped strategy engine.
- Preflight user strategy directories, reject symlink/path escapes, remove only user-owned strategy files, clear strategy overrides, reload the registry, invalidate runtime/cache state, and disable monitor rules that reference deleted strategies.
- Keep the existing single-strategy delete endpoint unchanged except for any shared validation/helper needed by the new route.

### 3. Build the management UI

- Replace the placeholder store dialog with a management dialog listing all strategies and their sources.
- Show delete actions only for custom/AI/composite strategies, with confirmation and visible failure state; built-ins remain protected and visibly labeled.
- Add a “回退初始版本” action with destructive confirmation and clear scope text.

### 4. Wire pool/query state and labels

- Rename the Screener entry and dialog title from “获取策略” to “管理策略”.
- Add typed API methods for delete and restore.
- On deletion, remove the strategy from the local pool and invalidate strategy queries; on restore, replace the pool with the returned 18 built-in IDs and invalidate related queries.

### 5. Verify the vertical slice

- Run the new targeted backend tests first, then existing strategy-delete/composite tests.
- Run frontend typecheck/build and relevant static/runtime tests.
- Run `git diff --check` and manually exercise: open management, delete a custom strategy, attempt built-in deletion, restore defaults, refresh, and verify the pool shows 18 built-ins while watchlist/account data is unchanged.

