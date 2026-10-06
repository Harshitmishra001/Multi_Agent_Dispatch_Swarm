# System Architecture & Verification Report (October 6, 2026)

**Repository:** `Harshitmishra001/Multi_Agent_Dispatch_Swarm`  
**Review Basis:** Source inspection, live test execution (`pytest`), frontend production build (`vite`), linter (`oxlint`), and live FastAPI `TestClient` probing.

---

## Executive Summary

The **Multi-Agent Emergency Dispatch Swarm** is a functional full-stack prototype that bridges LLM semantic extraction, vector deduplication (Qdrant), and mathematical optimization (Integer Linear Programming via PuLP) inside an event-driven LangGraph pipeline.

- **Automated Test Suite:** 13 of 13 tests passing (`tests/unit/`, `tests/integration/`, `tests/test_adversarial.py`).
- **Frontend Quality:** Vite production build succeeds in 4.89s; Oxlint passes with 0 errors and 0 warnings across 12 files.
- **Verdict:** **Strong, highly modular prototype and demonstration platform.** However, several critical operational, durability, and inventory reservation gaps prevent it from being classified as production-ready for real-world emergency dispatch without further hardening.

---

## 1. What is Fully Implemented & Working

### A. Core Agent Architecture & LangGraph Pipeline
* **5-Agent Workflow (`backend/graph/build_graph.py`):**
  1. `IngestionAgent` parses unstructured SMS/web reports into typed Pydantic models.
  2. `VerificationAgent` computes extraction confidence and queries Qdrant for semantic duplicates.
  3. `ResourceMatcher` runs an Integer Linear Program (PuLP) to maximize urgency-weighted coverage under capacity limits.
  4. `PlanSynthesizer` generates a natural language narrative and verifies grounding against real IDs.
  5. `EvaluatorAgent` computes deterministic metrics (coverage %, critical unmet count) and requests LLM fairness evaluation.
* **Human-in-the-Loop Interrupts:**
  - Configured via LangGraph's `interrupt_before=["human_review"]`.
  - Reports with low extraction confidence (`< 0.6`) or ambiguous duplicates pause execution, routing to the human review queue.
* **Bounded Evaluator Retry Loop:**
  - Evaluator failure triggers a revision loop back to `match_node` (bounded at `revision_count < 2`).
  - The in-place list mutation bug (`F-04`) was resolved by creating explicit list copies before mutating.

### B. Mathematical Resource Optimization (ILP via PuLP)
* **Objective Function (`backend/agents/resource_matcher.py`):**
  $$\text{Maximize } \sum (\text{urgency\_weight} - \min(\text{distance\_km}, 999.0)) \times \text{quantity}$$
  - Urgency weights: `CRITICAL: 4000`, `HIGH: 3000`, `MODERATE: 2000`, `LOW: 1000`.
  - Distance penalty calculated via the Haversine formula on spherical Earth coordinates.
* **Strict Constraints:**
  - Allocations per need cannot exceed the requested quantity.
  - Allocations per resource depot cannot exceed the available stock.
  - Solved dynamically via `PULP_CBC_CMD` or `COIN_CMD`.

### C. Vector Deduplication (Qdrant + Sentence-Transformers)
* **Local Disk Qdrant (`backend/db/vector_store.py`):**
  - Collection `needs` using 384-dimensional cosine similarity.
  - Embedded via `all-MiniLM-L6-v2` (`SentenceTransformer`).
  - Search filtered by `need_type` with a `0.85` similarity threshold.
  - Linked duplicate tracking merges `source_report_ids`.

### D. Ingestion & Regex Fallback
* **Prompt Injection Defense (`backend/security/input_sanitization.py`):**
  - Delimiter stripping (`</?raw_text>`) prevents tag breakout.
  - Prompt frames input as inert data.
* **Deterministic Fallback (`backend/agents/ingestion_agent.py`):**
  - If LM Studio is offline or outputs malformed JSON, regex/keyword extraction parses need categories (`medical`, `water`, `food`, `shelter`, `rescue`), urgency, quantities, and rough location.

### E. Full-Stack Operational Interface & Security
* **FastAPI Backend (`backend/api/`):**
  - OAuth2 Password Bearer / JWT token authentication (`/api/v1/auth/token`).
  - Password hashing with `bcrypt`.
  - Role-based dependencies: `get_current_reviewer` and `get_current_admin`.
  - Structured JSON audit logging to `audit.log`.
* **React/Leaflet Dashboard (`frontend/src/`):**
  - Dark-mode map interface with real-time SVG markers (red circle for needs, blue square for resources).
  - Review queue panel polling pending items every 5 seconds.
  - Review modal for approving or rejecting flagged needs.
  - Ingestion simulation modal with pre-configured emergency scenarios.

---

## 2. What is Fake, Mocked, Placeholder, or Incomplete

| Item | Component | File & Line | Status / Reality |
|---|---|---|---|
| **Inventory Reservation** | Database & Matching | `backend/api/routes.py:127-136` | **CRITICAL GAP:** Allocations are saved to `DBAllocation`, but `DBResource.quantity_available` is **never decremented**. Inventory is never reserved. Multiple reports can double-allocate the exact same supplies. |
| **Workflow Durability** | LangGraph State | `backend/graph/build_graph.py:122` | **EPHEMERAL:** Checkpointer uses `MemorySaver()`. If the server restarts, all in-memory paused human review threads disappear, breaking resumption. |
| **Background Processing** | API Task Execution | `backend/api/routes.py:200` | **IN-PROCESS ONLY:** Uses FastAPI `BackgroundTasks`. There is no Celery, Redis, or durable message broker. In-flight jobs are killed on server restart. |
| **Role Permission Bug** | Frontend/Auth | `backend/api/routes.py:293` vs `backend/db/models.py:84` | **PERMISSIONS BUG:** `GET /resources` requires `admin` role. Default demo user `alice` has `role="reviewer"`. As a result, the frontend map crashes with `403 Forbidden` when attempting to display depot markers. |
| **No Admin Seeded** | Database Init | `backend/db/models.py:76-90` | **MISSING SEED:** `init_db()` only creates `alice` (`reviewer`). No admin user exists out of the box. Admin endpoints (`POST /resources`, `POST /plans/{id}/override`) cannot be called without manual database manipulation. |
| **Dead Code Placeholder** | Resource Matcher | `backend/agents/resource_matcher.py:26-32` | **DEAD CODE:** `self.tiebreak_prompt` is initialized in `__init__`, but is never invoked anywhere in `process()` or the entire codebase. |
| **"Strong Tier" Router** | Model Router | `backend/config/model_router.py:7-20` | **PLACEHOLDER:** `get_llm("strong")` returns the exact same local model (`smollm3-3b`) as `get_llm("local")`. Multi-tier routing is simulated in name only. |
| **Rate Limiter Storage** | Security | `backend/security/rate_limiter.py:9` | **DEV ONLY:** In-memory `defaultdict(list)`. Does not share state across multi-worker Uvicorn or Gunicorn deployments. |
| **Unauthenticated Ingestion** | Security / PII | `backend/api/routes.py:171`, `backend/db/models.py:15` | **SECURITY GAP:** Public report endpoint `POST /reports` has no authentication or captcha. Reporter contact PII is stored unencrypted in plain text. |
| **Plan Override Audit** | Plan Management | `backend/api/routes.py:372-375` | **PRIMITIVE:** Plan override simply overwrites the text string `plan.rationale`. No separate audit table or immutable change history exists. |
| **Test Suite Mocking** | Pytest Suite | `tests/` | **NARROW TESTING:** All 13 tests mock LLM responses. There are 0 integration tests covering the FastAPI HTTP endpoints directly. |

---

## 3. Verification & Test Execution Results

### 1. Pytest Test Suite
```bash
pytest -v
======================= 13 passed, 3 warnings in 48.58s =======================
tests/integration/test_graph.py::test_graph_human_review_interrupt PASSED
tests/integration/test_graph.py::test_graph_evaluator_reject_loop PASSED
tests/test_adversarial.py::test_conflicting_needs PASSED
tests/test_adversarial.py::test_urgency_manipulation PASSED
tests/test_adversarial.py::test_format_injection PASSED
tests/unit/test_evaluator_agent.py::test_evaluator_agent_metrics PASSED
tests/unit/test_ingestion_agent.py::test_ingestion_agent_regex_fallback PASSED
tests/unit/test_ingestion_agent.py::test_ingestion_agent_llm_success PASSED
tests/unit/test_plan_synthesizer.py::test_plan_synthesizer_grounding_success PASSED
tests/unit/test_plan_synthesizer.py::test_plan_synthesizer_grounding_failure PASSED
tests/unit/test_resource_matcher.py::test_resource_matcher_urgency_priority PASSED
tests/unit/test_verification_agent.py::test_verification_agent_low_confidence PASSED
tests/unit/test_verification_agent.py::test_verification_agent_dedup PASSED
```

### 2. Frontend Production Build & Linting
```bash
cd frontend && npm run lint
Found 0 warnings and 0 errors. Finished in 66ms on 12 files.

cd frontend && npm run build
✓ 127 modules transformed.
dist/index.html                   0.45 kB │ gzip:   0.29 kB
dist/assets/index-CO_zO7_s.css   25.15 kB │ gzip:   6.15 kB
dist/assets/index-BSxisply.js   455.73 kB │ gzip: 142.13 kB
✓ built in 4.89s
```

### 3. API Endpoint Integration Probing
* `GET /health` & `GET /api/v1/health` -> `200 OK`
* `POST /api/v1/auth/token` (alice / reviewer_pass) -> `200 OK` (Valid JWT returned)
* `GET /api/v1/resources` (alice) -> `403 Forbidden` (`Admin permissions required`)
* `POST /api/v1/reports` -> `200 OK` (Accepted, processed in background with audit log emitted)
* `GET /api/v1/needs/pending-review` -> `200 OK`

---

## 4. Remediation Checklist for Production Readiness

1. **Transactional Inventory Reservation:**
   - In `_persist_graph_state`, execute an atomic database transaction: for each allocation, decrement `DBResource.quantity_available` with row locking (`with_for_update()`). If quantity is insufficient, reject or recalculate.
2. **Persistent Checkpointer:**
   - Replace LangGraph's `MemorySaver()` with `PostgresSaver` or `SqliteSaver` so interrupted states survive process restarts.
3. **Decoupled Task Queue:**
   - Migrate `BackgroundTasks` to Celery or ARQ with a Redis/RabbitMQ broker.
4. **Fix Role Permissions for Frontend:**
   - Change `GET /resources` dependency to `get_current_reviewer` so operators can view map resources, or seed a default admin user.
5. **Real Model Tier Split:**
   - Configure a remote API (e.g., Anthropic Claude or OpenAI) for the `strong` tier in `model_router.py` while keeping local SLMs for ingestion.
6. **Encrypted PII Storage:**
   - Use `cryptography.fernet` or SQLAlchemy encrypted types for `reporter_contact`.
