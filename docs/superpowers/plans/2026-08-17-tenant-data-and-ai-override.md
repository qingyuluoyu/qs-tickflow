# Tenant Data and AI Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep all user-created data and user-provided AI credentials isolated by account while using one server-owned default AI configuration and one shared, read-only market-data repository.

**Architecture:** Keep account identity and private application records in the transactional account database, keyed by an immutable `user_id`. Market prices, financial statements, securities master data, and server refresh configuration remain shared because they are public product data. AI execution resolves an immutable request-scoped profile: an encrypted user override when it exists, otherwise the server default; no request may mutate process-global settings.

**Tech Stack:** FastAPI, SQLite for the local deployment stage, PostgreSQL with row-level security before multi-worker public deployment, Pydantic schemas, React/TypeScript, existing request `UserIdentity` context.

## Global Constraints

- `phone` remains the unique account identifier; display name is not an account key.
- Passwords remain PBKDF2 hashes only; API keys are never returned after save and never written to logs.
- Do not create one physical database per end user; use mandatory `user_id` ownership and server-side authorization in one transactional database.
- Shared market data must never include user-owned selections, reports, strategies, preferences, or secrets.
- Use `user_id` in every private cache key, job payload, artifact path, log record, and query predicate.
- The existing file workspaces remain read-only migration sources until a separately released cleanup phase; do not delete them during migration.

---

### Task 1: Define and migrate the private-data schema

**Files:**
- Create: `backend/app/db/migrations/004_private_user_records.sql`
- Modify: `backend/app/services/account_store.py:75-84`
- Create: `backend/tests/test_private_user_store.py`

**Interfaces:**
- Consumes: `UserIdentity.id` from `backend/app/services/user_context.py`.
- Produces: transactional tables with `user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE` and repositories that always receive the authenticated `user_id`.

- [ ] **Step 1: Write the failing ownership tests**

```python
def test_private_record_cannot_be_read_by_another_user(store):
    store.save_preference("user-a", "theme", {"value": "light"})
    assert store.load_preference("user-b", "theme") is None

def test_upserted_ai_profile_is_scoped_to_its_owner(store):
    store.save_ai_profile("user-a", provider="openai_compat", model="a", encrypted_key=b"x")
    assert store.load_ai_profile("user-b") is None
```

- [ ] **Step 2: Run the tests and confirm they fail because the store methods do not exist**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_private_user_store.py -q`

Expected: two failures referring to missing private-record APIs.

- [ ] **Step 3: Add the versioned SQLite migration and minimal repository methods**

```sql
CREATE TABLE user_preferences (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preference_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, preference_key)
);

CREATE TABLE user_ai_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    encrypted_api_key BLOB,
    key_version INTEGER NOT NULL DEFAULT 1,
    use_server_default INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL
);
```

`AccountStore` must append migration version 4, use parameterized SQL, and expose only methods that accept a validated `user_id`.

- [ ] **Step 4: Run the targeted tests**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_private_user_store.py backend/tests/test_account_store.py -q`

Expected: all tests pass.

### Task 2: Resolve AI configuration per request without global mutation

**Files:**
- Modify: `backend/app/services/ai_provider.py:101-339`
- Modify: `backend/app/api/settings.py:58-326`
- Modify: `backend/app/secrets_store.py:19-87`
- Create: `backend/tests/test_ai_profile_isolation.py`

**Interfaces:**
- Consumes: authenticated `UserIdentity` context and `AccountStore.load_ai_profile(user_id)`.
- Produces: `ResolvedAiProfile(provider, base_url, model, api_key, source)` where `source` is `server_default` or `user_override`.

- [ ] **Step 1: Write failing request-context tests**

```python
def test_user_without_override_resolves_server_default(profile_service, server_default):
    assert profile_service.resolve("user-a") == server_default

def test_user_override_never_changes_another_users_or_server_default(profile_service, server_default):
    profile_service.save_override("user-a", provider="openai_compat", base_url="https://api.example.com", model="custom", api_key="secret")
    assert profile_service.resolve("user-a").model == "custom"
    assert profile_service.resolve("user-b") == server_default
```

- [ ] **Step 2: Run tests and confirm they fail before implementation**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_ai_profile_isolation.py -q`

Expected: failures for missing `ResolvedAiProfile` / override service.

- [ ] **Step 3: Implement explicit profile resolution**

```python
profile = ai_profiles.resolve(current_user().id)
client = AsyncOpenAI(api_key=profile.api_key, base_url=normalize_openai_base_url(profile.base_url), timeout=timeout, max_retries=0)
```

Remove assignments such as `settings.ai_model = req.model` from authenticated settings endpoints. Settings responses may return `has_user_override` and a masked key, but never raw keys. The server default remains environment/deployment configuration and is not editable by ordinary users.

- [ ] **Step 4: Add SSRF validation for user-supplied base URLs**

Reject non-HTTPS URLs, credentials in URLs, loopback/private/link-local/multicast IP destinations, DNS answers in private ranges, and redirects to a disallowed destination. Set finite connect/read timeouts and disable automatic credential forwarding on redirects.

- [ ] **Step 5: Run API and provider regressions**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_ai_profile_isolation.py backend/tests/test_ai_provider.py backend/tests/test_auth_api.py -q`

Expected: all tests pass.

### Task 3: Move private user content behind owner-scoped repositories

**Files:**
- Modify: `backend/app/services/watchlist.py`
- Modify: `backend/app/services/preferences.py`
- Modify: `backend/app/services/json_report_store.py`
- Modify: `backend/app/api/watchlist.py`, `backend/app/api/settings.py`, `backend/app/api/strategy.py`, `backend/app/api/backtest.py`, `backend/app/api/monitor_rules.py`
- Create: `backend/tests/test_private_data_e2e.py`

**Interfaces:**
- Consumes: `request.state.user.id` and `request_data_root(request)` only for transitional artifacts.
- Produces: owner-scoped watchlists, preferences, reports, strategy definitions, backtest result metadata, monitor rules, and alerts.

- [ ] **Step 1: Write two-account end-to-end tests**

```python
def test_private_resources_are_invisible_to_a_different_authenticated_user(alice, bob):
    created = alice.post("/api/watchlist", json={"symbol": "600000.SH"})
    assert created.status_code == 200
    assert [row["symbol"] for row in bob.get("/api/watchlist").json()["symbols"]] == []

    report = alice.post("/api/financials/reports", json={"symbol": "600000.SH", "content": "private"})
    assert report.status_code == 200
    assert bob.get(f"/api/financials/reports/{report.json()['id']}").status_code == 404
```

- [ ] **Step 2: Verify RED state**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_private_data_e2e.py -q`

Expected: failing test for the first private resource not yet represented by an owner-scoped database record.

- [ ] **Step 3: Implement one repository at a time**

Each query must have an explicit owner predicate:

```sql
SELECT payload_json FROM user_reports WHERE user_id = ? AND report_id = ?;
```

Do not accept `user_id` from request JSON or query parameters. Derive it only from the authenticated session. Store large generated artifacts under `data/users/<uuid>/artifacts/`, with the database record as the authority for ownership and path lookup.

- [ ] **Step 4: Run isolation and existing user-data regressions**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_account_e2e.py backend/tests/test_backtest_user_isolation.py backend/tests/test_private_data_e2e.py -q`

Expected: all tests pass.

### Task 4: Make all background work tenant-safe and protect server controls

**Files:**
- Modify: `backend/app/jobs/daily_pipeline.py:1163-1359`
- Modify: `backend/app/api/settings.py:1464-1508`
- Modify: `backend/app/tickflow/client.py:25-105`
- Modify: `backend/app/services/pipeline_jobs.py`
- Create: `backend/tests/test_scheduled_review_isolation.py`

**Interfaces:**
- Consumes: a persisted job payload containing `job_id`, `user_id`, request trace, immutable AI profile snapshot reference, and status.
- Produces: owner-scoped scheduled review/report artifacts and server-only market-data client configuration.

- [ ] **Step 1: Write failing scheduler tests**

```python
async def test_scheduled_review_binds_its_owner_context(monkeypatch, store):
    job = store.create_review_job(user_id="user-a", hour=16, minute=0)
    await run_review_job(job.id)
    assert store.list_reports("user-a")
    assert store.list_reports("user-b") == []
```

- [ ] **Step 2: Confirm the test fails against the shared `scheduled_review` job**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_scheduled_review_isolation.py -q`

Expected: failure demonstrating that a global job ID cannot represent two owners.

- [ ] **Step 3: Implement a durable owner-scoped job model**

Use IDs such as `scheduled_review:<user_uuid>`, persist lifecycle fields (`pending`, `running`, `completed`, `failed`, timestamps, attempts, error code), and call `set_current_user(user, user_root)` around the job execution. Do not use a context fallback to shared `data/user_data`.

Keep market-data API credentials and connection pools server-owned. Remove ordinary-user ability to save, switch, or reset market-data provider credentials. If user-provided AI keys are allowed, build clients from the immutable resolved profile per request/task rather than process globals.

- [ ] **Step 4: Run background-job and authorization regressions**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_scheduled_review_isolation.py backend/tests/test_monitor_runtime.py backend/tests/test_server_preferences.py -q`

Expected: all tests pass.

### Task 5: Safe migration, deployment, and production verification

**Files:**
- Create: `backend/app/services/private_data_migration.py`
- Create: `backend/tests/test_private_data_migration.py`
- Modify: `docs/deployment.md`

**Interfaces:**
- Consumes: legacy per-user workspace files and the authenticated user record list.
- Produces: idempotent migration checkpoints and a verified record count/hash summary without copying secrets into logs.

- [ ] **Step 1: Write failing idempotency tests**

```python
def test_migration_imports_a_legacy_watchlist_once_and_preserves_owner(tmp_path):
    first = migrate_user_workspace("user-a", tmp_path)
    second = migrate_user_workspace("user-a", tmp_path)
    assert first.imported_watchlists == 1
    assert second.imported_watchlists == 0
```

- [ ] **Step 2: Implement expand-migrate-contract**

Create new tables first, dual-read during the migration window, write new records to the database, and retain the original workspace files untouched. Record per-user migration version and checksum. Only a later independent release may stop legacy reads after a verified export and rollback window.

- [ ] **Step 3: Run release checks**

Run: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_private_data_migration.py backend/tests/test_account_e2e.py backend/tests/test_ai_profile_isolation.py backend/tests/test_scheduled_review_isolation.py -q`

Run: `frontend\\node_modules\\.bin\\tsc.cmd -b; frontend\\node_modules\\.bin\\vite.cmd build`

Expected: all specified backend tests and the production frontend build pass. Before a multi-worker public launch, apply the equivalent schema to PostgreSQL and enforce row-level security with a database role that cannot bypass ownership policies.

## Plan self-review

- Spec coverage: private data, default-vs-user AI, market-data ownership, background tasks, migration, and release verification are covered by Tasks 1–5.
- Explicitly shared data: kline, financial statements, securities master, market regime, aggregate public rankings, and server refresh settings are intentionally not user-owned.
- No cleanup/deletion is part of this plan; legacy files remain as a rollback source until a later contract release.
