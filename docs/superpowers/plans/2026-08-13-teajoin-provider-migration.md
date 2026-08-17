# TeaJoin Provider Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace TickFlow as the only production market-data supplier with TeaJoin while preserving the product's internal API contracts and financial-data traceability.

**Architecture:** Keep React and the product-owned FastAPI `/api/*` stable. Introduce TeaJoin as a first-class, typed provider behind the existing provider boundary, normalize each TeaJoin response before persistence, and remove all silent TickFlow fallbacks dataset by dataset. Cut over in independently verified slices so unsupported TeaJoin data never appears as fabricated market data.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, httpx, Polars, DuckDB, Parquet, pytest, React 18, TypeScript.

## Global Constraints

- Do not expose `TEAJOIN_API_KEY` to browser code, logs, test output, or committed files.
- Every persisted market row records source, market, asset type, effective date, observed-at time, and source version where TeaJoin returns it.
- Financial and backtest reads must obey announcement-time availability; never replace historical point-in-time data with later revisions.
- Missing, stale, rate-limited, unauthorized, and malformed upstream data must remain distinct error states.
- Do not silently fall back to TickFlow once a TeaJoin dataset has been selected for the production path.
- Preserve existing data until TeaJoin shadow checks and rebuilt enriched data pass row, schema, unit, and indicator reconciliation.

---

### Task 1: TeaJoin day-frequency contract

**Files:**
- Modify: `backend/tests/test_teajoin_provider.py`
- Modify: `backend/app/data_providers/custom/config.py`
- Modify: `backend/app/data_providers/custom/provider.py`
- Modify: `data/data_sources/teajoin.yaml`

**Interfaces:**
- Consumes: TeaJoin `fields` + `items` two-dimensional responses and `params.ts_code/start_date/end_date` request contract.
- Produces: normalized daily and adjustment-factor `pl.DataFrame` objects with date fields parsed from `%Y%m%d`.

- [ ] Write failing tests for nested TeaJoin body parameters and two-dimensional response mapping.
- [ ] Run `uv run pytest tests/test_teajoin_provider.py -v` and confirm the nested-date tests fail before implementation.
- [ ] Add constrained nested request-path support and update the TeaJoin configuration with the verified API field names.
- [ ] Run the focused tests and the data-source test endpoint using the configured TeaJoin key.

### Task 2: TeaJoin securities and financials provider

**Files:**
- Create: `backend/app/data_providers/teajoin_provider.py`
- Modify: `backend/app/data_providers/base.py`
- Modify: `backend/app/data_providers/registry.py`
- Modify: `backend/tests/test_teajoin_provider.py`

**Interfaces:**
- Consumes: `stock_basic`, `daily`, `adj_factor`, `income`, `balancesheet`, `cashflow`, and `daily_basic` TeaJoin endpoints.
- Produces: `get_instruments`, `get_daily`, `get_adj_factors`, and `get_financials` typed provider methods with explicit TeaJoin request contracts.

- [ ] Write failing provider tests using HTTP transport fixtures for successful, empty, and API-error responses.
- [ ] Implement the minimum provider and explicit TeaJoin response validation.
- [ ] Verify field, unit, and date normalization tests pass.

### Task 3: Switch the stock daily pipeline

**Files:**
- Modify: `backend/app/services/instrument_sync.py`
- Modify: `backend/app/services/kline_sync.py`
- Modify: `backend/app/services/financial_sync.py`
- Modify: `backend/app/jobs/daily_pipeline.py`
- Modify: `backend/tests/test_teajoin_pipeline.py`

**Interfaces:**
- Consumes: registered TeaJoin provider and persisted preferences.
- Produces: TeaJoin-only stock instruments, daily bars, factors, daily basics, and financial writes; explicit errors if the configured provider lacks a dataset.

- [ ] Write failing tests proving a missing TeaJoin dataset does not call TickFlow.
- [ ] Implement explicit provider routing and source metadata persistence.
- [ ] Run affected integration tests against temporary Parquet storage.

### Task 4: Rebuild and reconcile day-frequency storage

**Files:**
- Create: `backend/app/services/teajoin_reconciliation.py`
- Create: `backend/tests/test_teajoin_reconciliation.py`
- Modify: `backend/app/api/data.py`
- Modify: `docs/configuration.md`

**Interfaces:**
- Consumes: TeaJoin staging partitions and current active partitions.
- Produces: reconciliation report containing row counts, missing symbols, duplicate keys, unit checks, latest dates, and indicator deltas before atomic activation.

- [ ] Write failing reconciliation tests for duplicates, stale data, and incompatible units.
- [ ] Implement atomic stage-validate-promote processing and report API.
- [ ] Shadow-run a chosen trading-date range and preserve the report artifact.

### Task 5: Realtime, minute, index, ETF, and depth

**Files:**
- Modify: `backend/app/data_providers/teajoin_provider.py`
- Modify: `backend/app/services/quote_service.py`
- Modify: `backend/app/services/kline_sync.py`
- Modify: `backend/app/services/index_sync.py`
- Modify: `backend/app/services/depth_service.py`
- Modify: `backend/tests/test_teajoin_realtime.py`
- Modify: `backend/tests/test_teajoin_minute.py`

**Interfaces:**
- Consumes: production-verified TeaJoin endpoints for realtime snapshots, minute bars, index/ETF universes, and depth if licensed.
- Produces: source-specific freshness metadata and fail-closed feature flags for unavailable depth or asset classes.

- [ ] Capture real TeaJoin contracts in redacted fixtures before coding each dataset.
- [ ] Write failing tests for market-hours behavior, empty snapshots, data staleness, and rate limits.
- [ ] Implement one dataset at a time and run end-to-end monitoring/backtest checks.
- [ ] Disable depth, intraday, index, or ETF UI entry points if TeaJoin cannot provide the exact licensed data.

### Task 6: Remove TickFlow supplier paths and production hardening

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/settings.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/settings/*`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `docs/deployment.md`

**Interfaces:**
- Consumes: provider health and dataset capability reports.
- Produces: TeaJoin-only operational settings, health telemetry, and no TickFlow credentials or silent fallbacks.

- [ ] Write failing settings and authorization tests.
- [ ] Remove TickFlow credential and tier UI only after all affected datasets are live.
- [ ] Run full backend tests, frontend lint/build, deployment smoke test, and rollback rehearsal.

## Self-Review

- Day-frequency delivery is independently testable before realtime/depth work starts.
- Every dataset replacement has a contract, test, source metadata, and failure behavior.
- No plan item relies on a placeholder or assumes TeaJoin depth/index/ETF availability without verification.
