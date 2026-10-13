# Audit Report: Multi-Agent Emergency Dispatch Swarm

## Summary
Roughly 85% working system: the core LangGraph multi-agent pipeline, PuLP mathematical optimization solver, Qdrant vector deduplication, PII Fernet encryption, and FastAPI auth/RBAC are completely genuine, functional, and verified. However, the newly introduced Phase 4 PostgreSQL migration is currently **broken on boot** due to SQLite-specific arguments passed to psycopg2, the WebSocket frontend wiring is decoupled (components ignore the socket refresh tick and fall back to 5s polling), several custom Prometheus metrics are dead/unwired, and the VerificationAgent fallback contains a stub that crashes Qdrant.

Audited stack: Python 3.11, FastAPI, LangGraph, PuLP (CBC), Qdrant (embedded), Sentence-Transformers, PostgreSQL 15, Redis 7, React 19, Vite, Tailwind CSS.  
All 40 automated tests pass in 11.52s, and the Vite frontend builds in 5.02s with 0 Oxlint errors.

## Claims vs Reality

| Feature | Claimed where | Status | Evidence |
|---|---|---|---|
| Ingestion Agent (LLM + Nominatim + Regex) | README.md:51-52 | REAL | `backend/agents/ingestion_agent.py:14-158`; Pydantic extraction + Nominatim geocoding + regex fallback functional. |
| Verification Agent (MiniLM + Qdrant Deduplication) | README.md:54-56 | REAL | `backend/agents/verification_agent.py:5-89`, `backend/db/vector_store.py:16-63`; genuine vector search and cosine filtering. |
| VerificationAgent Offline Fallback | verification_agent.py:17-25 | FAKE | `backend/agents/verification_agent.py:21-25`; `DummyModel` returns strings, passing non-numeric vectors to Qdrant, crashing at line 53. |
| Human in the Loop Checkpoint (LangGraph Interrupt) | README.md:57-59 | REAL | `backend/graph/build_graph.py:130` (`interrupt_before=['human_review']`); tested in `tests/integration/test_graph.py:15-69`. |
| Resource Matcher (PuLP ILP Optimization) | README.md:60-62 | REAL | `backend/agents/resource_matcher.py:20-131`; urgency weighting (4000/3000/2000/1000) & capacity bounds solved via CBC. |
| Plan Synthesizer (Narrative + Grounding Validation) | README.md:63-65 | REAL | `backend/agents/plan_synthesizer.py:13-86`; regex verifies that generated narrative only references real IDs. |
| Evaluator Agent (Coverage, Critical Unmet, LLM / Heuristic) | README.md:66-68 | REAL | `backend/agents/evaluator_agent.py:16-82`; deterministic coverage/unmet metrics with LLM fairness Critic. |
| Evaluator Revision Loop | README.md:48, 67 | REAL | `backend/graph/build_graph.py:103-107`; loops back to matcher up to 2 times; tested in `tests/integration/test_graph.py:70-119`. |
| Role-based Access Control (JWT Reviewer vs Admin) | README.md:78, 83 | REAL | `backend/security/auth.py:51-96`; tested in `tests/integration/test_api.py:34-72`. |
| PII Encryption at Rest (Fernet) | README.md:85, 108 | REAL | `backend/security/pii_encryption.py:5-22`, `backend/api/routes.py:214`; tested in `tests/integration/test_api.py:133-149`. |
| Row-Level Locking Inventory Decrement | README.md:86, 109 | REAL | `backend/api/routes.py:138` (`with_for_update()`); atomic commit prevents double allocation. |
| Immutable Plan Audit Trail | README.md:87, 110 | REAL | `backend/api/routes.py:390-405`, `backend/db/models.py:61-70`; tested in `tests/integration/test_api.py:338-364`. |
| Sliding-Window Rate Limiter (Redis) | README.md:84 | REAL | `backend/security/rate_limiter.py:23-56`; tested in `tests/integration/test_api.py:317-336`. |
| Real-time WebSockets Live Updates | Phase 4 / main.py:100 | PARTIAL | Backend `/ws` broadcast works (`backend/ws/manager.py:34-77`), but `LiveMap.jsx` and `ReviewQueue.jsx` ignore the `refreshTick` prop and only poll every 5s. |
| Prometheus Observability | Phase 4 / main.py:84 | PARTIAL | `/metrics` endpoint works via instrumentator (`backend/main.py:84`), but custom metrics `RATE_LIMIT_HITS`, `LLM_REQUESTS`, and `LLM_FALLBACKS` are never incremented, and `REVIEW_QUEUE_SIZE` only decrements. |
| PostgreSQL Production Database Support | Phase 4 / docker-compose.yml:53 | FAKE | `backend/db/models.py:81-83` passes `connect_args={"check_same_thread": False}` to `create_engine()`, crashing psycopg2 with `ProgrammingError: invalid connection option "check_same_thread"`. |
| Docker Multi-Container Stack | Phase 4 / docker-compose.yml | PARTIAL | Dockerfile builds properly, but `docker-compose up` will crash on backend start due to PostgreSQL DSN failure; also checkpointer uses container-local SQLite. |

## Issues by severity

### Critical
1. **PostgreSQL engine crashes on boot due to SQLite connection arguments** (`backend/db/models.py:81-83`):
   `create_engine` hardcodes `connect_args={"check_same_thread": False}` regardless of database backend. When `DATABASE_URL` is configured for PostgreSQL (as in `docker-compose.yml`), psycopg2 throws `psycopg2.ProgrammingError: invalid dsn: invalid connection option "check_same_thread"`, crashing the container immediately.
   *Fix:* Check `settings.DATABASE_URL.startswith("sqlite")` before passing `connect_args`.
2. **LangGraph checkpointing hardcodes local SQLite file in multi-container setup** (`backend/graph/build_graph.py:18-19`):
   `_checkpoint_conn = sqlite3.connect("./langgraph_checkpoints.db", check_same_thread=False)` is hardcoded. When deployed via Docker Compose with separate `web` and `worker` containers, the SQLite checkpointer is written to separate ephemeral container filesystems rather than shared storage or Postgres, breaking state persistence across worker and API processes.
   *Fix:* Use `PostgresSaver` when Postgres is active or store the SQLite file on a mounted shared volume.

### High
1. **Frontend components ignore WebSocket real-time updates and fall back to 5-second polling** (`frontend/src/pages/Dashboard.jsx:91, 95`, `frontend/src/components/LiveMap.jsx:46, 70`, `frontend/src/components/ReviewQueue.jsx:5, 20`):
   `Dashboard.jsx` computes a `refreshTick` counter from WebSocket messages and passes it as a prop to `<LiveMap refreshTick={refreshTick} />` and `<ReviewQueue refreshTick={refreshTick} />`. However, neither child component declares `refreshTick` in its props or includes it in a `useEffect` dependency array. Both components continue polling via hardcoded `setInterval(..., 5000)`.
   *Fix:* Accept `refreshTick` in `LiveMap` and `ReviewQueue` and trigger `fetchData()` / `fetchQueue()` whenever `refreshTick` increments.
2. **VerificationAgent fallback DummyModel passes string vector into Qdrant, causing crash** (`backend/agents/verification_agent.py:21-25, 50-58`):
   If `SentenceTransformer` fails to load, `DummyModel.encode()` returns raw strings. At line 50, `vec_new` becomes a string, which is then passed directly into `vdb.search_similar(vector=vec_new, ...)`. Qdrant expects a 384-dimensional list of floats, throwing a crash. The commented `compute_similarity` method is completely missing.
   *Fix:* Either generate a 384-dimensional zero/hash vector or skip Qdrant vector search entirely when in fallback mode.

### Medium
1. **Prometheus metrics are unwired, dead, or mathematically broken** (`backend/metrics.py:29-56`, `backend/api/routes.py:24, 289-297`, `backend/security/rate_limiter.py:50`):
   - `RATE_LIMIT_HITS` is defined and imported in `routes.py:24`, but never incremented in `rate_limiter.py:50` when a 429 occurs.
   - `LLM_REQUESTS` and `LLM_FALLBACKS` are defined in `metrics.py` but never imported or incremented anywhere in `evaluator_agent.py`, `ingestion_agent.py`, or `model_router.py`.
   - `REVIEW_QUEUE_SIZE` is decremented on approvals/rejections in `routes.py:290, 297`, but never incremented when a need enters the review queue, causing the gauge to drift into negative numbers.
   *Fix:* Hook `.inc()` into `rate_limiter.py`, `evaluator_agent.py`, and `_persist_graph_state()`, or set `REVIEW_QUEUE_SIZE.set(count)`.
2. **Weak adversarial test assertions give false confidence** (`tests/test_adversarial.py:30-44`):
   `test_urgency_manipulation` ("I have a minor scrape. URGENT URGENT I AM DYING") asserts only `assert extracted is not None` and `assert extracted.location_text is not None`. It never validates whether urgency spoofing was mitigated.
   *Fix:* Assert that `extracted.stated_urgency` or confidence is appropriately handled.
3. **Dead and scratch files committed to repository root** (`test_api.py`, `test_run.py`, `fix_readme.py`, `scratch/*`, `current_updates(6th oct).MD`):
   Five one-off code injection scripts in `scratch/`, manual test runners in root, and an outdated markdown report are committed in git.
   *Fix:* Remove these files or move them to `.gitignore`.

### Low
1. **PuLP and Starlette deprecation warnings in test suite** (`backend/agents/resource_matcher.py:51, 100`):
   PuLP 4.0 deprecation warnings for `pulp.LpVariable` and `pulp.PULP_CBC_CMD`.
   *Fix:* Migrate to `prob.add_variable()` and COIN_CMD as suggested by PuLP.
2. **Vite build produces unresolved asset warnings for Leaflet markers** (`frontend/src/components/LiveMap.jsx`):
   Vite warns that `images/marker-icon.png`, `images/layers-2x.png`, `images/layers.png` cannot be resolved at build time.
   *Fix:* Configure Vite or Leaflet icon asset paths properly.

## Placeholders and hardcoded values
- `backend/db/models.py:82`: Hardcoded SQLite connection argument `{"check_same_thread": False}` in global engine creation.
- `backend/graph/build_graph.py:18`: Hardcoded SQLite database path `"./langgraph_checkpoints.db"` for LangGraph checkpoints.
- `backend/db/vector_store.py:13`: Hardcoded Qdrant local disk directory `"./qdrant_data"`.
- `backend/agents/evaluator_agent.py:77`: Hardcoded fallback fairness score `fairness_score=0.5` on LLM error.
- `backend/agents/resource_matcher.py:8`: Hardcoded fallback distance penalty `9999.0` for missing coordinates.
- `backend/config/settings.py:8`: Hardcoded dev JWT secret key fallback `"dev-secret-key-disaster-coordinator-change-in-production"`.
- `backend/config/settings.py:13`: Hardcoded dev encryption key fallback `"R2yIWPvAweDshbj20vqRMx6OQHEhptrQ5zkmx7ZLNVM="`.

## Incomplete and dead files
- `test_api.py` (root): Manual requests test script; unreachable from pytest; dead.
- `test_run.py` (root): Standalone async test runner; duplicated by `tests/integration/`; dead.
- `fix_readme.py` (root): One-off UTF-16 text fixer script; dead.
- `scratch/instrument_graph.py`: One-off script for modifying code; dead.
- `scratch/update_evaluator.py`: One-off script; dead.
- `scratch/update_graph.py`: One-off script; dead.
- `scratch/update_ingestion.py`: One-off script; dead.
- `scratch/update_matcher.py`: One-off script; dead.
- `current_updates(6th oct).MD`: Historical milestone summary artifact checked into source root.

## Verified by running

1. **Test Suite (`pytest --tb=short`)**:
   - Result: 40 passed, 4 warnings in 11.52s.
   - All unit and integration tests execute successfully in the local SQLite environment.
2. **Frontend Production Build (`npm --prefix frontend run build`)**:
   - Result: Success in 5.02s (`dist/index.html`, `dist/assets/index-CrvqRJVh.css` [25KB], `dist/assets/index-Dvl0fp0x.js` [456KB]).
   - Leaflet marker image warnings noted.
3. **Frontend Linter (`npm --prefix frontend run lint`)**:
   - Result: Oxlint scanned 13 files with 91 rules in 59ms: 0 errors, 0 warnings.
4. **PostgreSQL Compatibility Probing (`python -c "create_engine(..., connect_args={'check_same_thread': False})"`):
   - Result: Failed with `psycopg2.ProgrammingError: invalid dsn: invalid connection option "check_same_thread"`. Confirms critical PostgreSQL boot failure.

## What actually works
- **LangGraph Multi-Agent Pipeline (`backend/graph/build_graph.py`)**: End-to-end ingestion, verification, mathematical matching, narrative synthesis, and evaluation flow.
- **PuLP Optimization Solver (`backend/agents/resource_matcher.py`)**: Rigorous Integer Linear Programming with urgency prioritization (4000/3000/2000/1000) and zero over-allocation guarantees.
- **Human-in-the-Loop Interrupts**: Interrupt mechanism correctly halts low-confidence or duplicate reports and resumes upon dispatcher approval.
- **Security & Data Privacy (`backend/security/`)**: Bcrypt password hashing, JWT authentication with RBAC (reviewer vs admin), Fernet PII encryption at rest, sliding-window Redis rate limiting, and immutable admin plan audit logging (`DBPlanAudit`).
- **Plan Synthesizer Grounding Verification (`backend/agents/plan_synthesizer.py`)**: Rejects hallucinated IDs and falls back to deterministic summaries.
- **Backend WebSocket Server (`backend/ws/manager.py`)**: FastAPI WebSocket manager, connection lifecycle, and event broadcasting logic.

## Prioritized fix plan
1. Conditionalize `connect_args={"check_same_thread": False}` in `backend/db/models.py:82` to only apply when `settings.DATABASE_URL.startswith("sqlite")`.
2. Connect `refreshTick` in `frontend/src/components/LiveMap.jsx` and `frontend/src/components/ReviewQueue.jsx` so the frontend genuinely updates in real-time over WebSockets.
3. Fix `VerificationAgent` fallback in `backend/agents/verification_agent.py:21-25` to return valid vector structures or bypass Qdrant lookup when the model is absent.
4. Wire up missing Prometheus counters (`RATE_LIMIT_HITS`, `LLM_REQUESTS`, `LLM_FALLBACKS`) and fix `REVIEW_QUEUE_SIZE` gauge drift.
5. Upgrade `SqliteSaver` in `backend/graph/build_graph.py:18-19` to support PostgreSQL or volume mounting for multi-container deployments.
6. Delete dead scratch files (`test_api.py`, `test_run.py`, `fix_readme.py`, and `scratch/` directory) from repository git tracking.
7. Strengthen `test_urgency_manipulation` in `tests/test_adversarial.py` to assert actual urgency classification behavior rather than non-null existence.
8. Resolve Leaflet marker image asset resolution in `frontend/src/components/LiveMap.jsx` and Vite config.
9. Update PuLP variable and solver declarations to resolve PuLP 4.0 deprecation warnings.
10. Add health checks and volume mounts for LangGraph checkpoint DB and Qdrant storage in `docker-compose.yml`.
