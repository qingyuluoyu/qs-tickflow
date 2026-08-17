# Production Launch Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the locally-fixable security, operability, and reproducibility blockers before deploying the account-isolated C-end product.

**Architecture:** Keep the existing single-container FastAPI/React deployment and SQLite account store. Add persistent registration throttling inside the same account transaction, add same-origin production security headers, expose a dependency-aware readiness endpoint, and make the Docker build fail closed when lockfiles cannot be honored.

**Tech Stack:** Python 3.11, FastAPI, SQLite, pytest, React/Vite, Docker Compose.

## Global Constraints

- Preserve account workspace isolation and shared read-only market data.
- Do not add a second database, cache service, reverse proxy, or dependency.
- Do not print or commit TeaJoin credentials or user data.
- Do not claim phone ownership verification, TLS, or off-site backup without their external services.
- Every behavior change follows a failing-test-first cycle.

---

### Task 1: Persistent anonymous registration throttling

**Files:**
- Create: `backend/app/db/migrations/003_registration_rate_limit.sql`
- Modify: `backend/app/services/account_store.py`
- Modify: `backend/app/api/auth.py`
- Test: `backend/tests/test_account_store.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Produces: `RegistrationRateLimited(retry_after: int)` and `AccountStore.enter(..., registration_key: str | None)`.
- Behavior: existing-account login is not counted; a sixth new account from one opaque client key in one hour is rejected before password hashing and insertion.

- [x] Write tests proving five registrations succeed, the sixth fails, a normal login still succeeds, and a new time window allows registration.
- [x] Run the focused tests and verify failure because persistent registration throttling does not exist.
- [x] Add migration 003 and atomically consume a registration slot only when the phone is new.
- [x] Map the domain exception to HTTP 429 with `Retry-After` without logging phone/password.
- [x] Run focused account/auth tests; targeted Ruff found no new naming issue after correction, while repository-wide historical lint debt remains.

### Task 2: Same-origin production response hardening

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_security_headers.py`

**Interfaces:**
- Produces: default-deny cross-origin behavior unless `CORS_ORIGINS` explicitly lists origins.
- Produces: CSP, frame denial, MIME sniffing denial, referrer policy, permissions policy, and conditional HSTS headers.

- [x] Write TestClient tests for default CORS denial, explicit-origin CORS, security headers, and trusted HTTPS HSTS.
- [x] Run tests and verify the wildcard CORS/security-header expectations fail.
- [x] Add parsed `cors_origins` settings and conditional CORS middleware.
- [x] Add security headers without changing JSON contracts or static asset routes.
- [x] Run focused middleware tests; touched legacy modules still expose pre-existing import-format lint debt.

### Task 3: Readiness and reproducible container deployment

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Test: `backend/tests/test_readiness.py`
- Create: `backend/tests/test_deployment_contract.py`

**Interfaces:**
- Produces: `GET /api/health` returning 200 only after account store and repository initialization, while `/health` remains a lightweight liveness endpoint.
- Produces: Compose healthcheck against `/api/health` and lockfile-fail-closed dependency installs.

- [x] Write failing readiness and static deployment-contract tests.
- [x] Run them and verify missing `/api/health`, missing healthcheck, and dependency fallback failures.
- [x] Implement readiness without triggering market-data pulls or database writes.
- [x] Remove unlocked dependency fallbacks, pin build tools, and add a Compose healthcheck.
- [x] Validate Compose configuration; Docker build was attempted but the local Docker Desktop daemon is unavailable.

### Task 4: Release verification and operator checklist

**Files:**
- Modify: `docs/deployment.md`
- Verify: backend test suite, Ruff on touched files, frontend production build, running `/health` and `/api/health`.

**Interfaces:**
- Produces: an explicit checklist for TLS proxy headers, TeaJoin key/provider health, qingshu101 host/key, SMS/phone ownership verification decision, backups, restore drill, and data-license confirmation.

- [x] Document only external steps that cannot be truthfully implemented locally.
- [x] Run full backend tests, frontend lint/build, and production dependency audit.
- [x] Restart the local backend and check liveness/readiness through the frontend proxy.
- [x] Report pass/fail evidence, compatibility, cost, rollback, and remaining external blockers.

## Self-Review

- Spec coverage: registration abuse, browser hardening, readiness, deterministic builds, and external launch dependencies are covered.
- Placeholder scan: no deferred code placeholders are used; external services are explicitly identified as operator actions.
- Type consistency: the account exception carries integer retry seconds from store to API; health routes remain dictionaries/JSON responses; no frontend API contract changes are required.
