# Multi-Agent Emergency Dispatch Swarm

Emergency dispatch is currently one of India's biggest hurdles. Incidents like the Satya Niketan building collapse and floods across North India showed how chaotic ground reality gets when disaster strikes. I started thinking about how India is leading in technology across so many sectors, and is still remarkably slow when it comes to quick emergency response and utilizing that tech where every minute counts. 

During emergencies, information floods in from SMS, phone calls, and social media. People are trapped, supplies run out, and the reports coming in are messy, emotional, and full of duplicates. Right now dispatchers are juggling spreadsheets, phone calls, and manual guesswork. That is where this idea came in: what if we let AI agents read the chaotic reports, verify what is real, remove duplicates, and calculate exact dispatch plans, while keeping a human dispatcher in the loop to sign off on uncertain cases? 

This led me to build this project: an autonomous multi-agent emergency coordination system built with LangGraph, FastAPI, and React.

---

## The Core Problem with Pure LLMs in Emergencies

When I started designing this, my first instinct was to see if an LLM could match supplies to victims directly. I quickly realized that was a dangerous mistake. 

LLMs are great at reading messy language and understanding what people need, and they are completely unreliable at constraint mathematics. When an LLM allocates resources, it hallucinates quantities, sends medical supplies to the wrong places, and ignores physical capacity limits. 

Because of that, I separated the intelligence into two distinct layers:
1. Language and verification: LLMs handle reading the text, extracting needs, and writing human summaries.
2. Math and logistics: An Integer Linear Programming (ILP) solver handles the actual resource allocation. The solver treats allocation as an optimization problem, maximizing urgency-weighted coverage while respecting exact depot inventory and road distances.

---

## How the 5-Agent Pipeline Works

A raw emergency report moves through five distinct agents connected via a LangGraph state machine:

```
[Raw Report] 
      │
      ▼
1. Ingestion Agent (LLM + Nominatim Geocoder + Regex Fallback)
      │
      ▼
2. Verification Agent (Sentence Transformers + Qdrant Vector Store)
      │
      ├─► Confidence < 0.6 or Duplicate ──► [Human Review Queue] ──► (Dispatcher Approves)
      │                                                                        │
      ▼ (High Confidence & Unique)                                            │
3. Resource Matcher (PuLP Integer Linear Programming) ◄────────────────────────┘
      │
      ▼
4. Plan Synthesizer (LLM Narrative + Grounded ID Verification)
      │
      ▼
5. Evaluator Agent (OpenRouter Ling-3.1-Flash or Local Model Critic)
      │
      ├─► Passed (Fairness & Coverage OK) ──► [Dispatch Plan Finalized & Broadcast]
      └─► Failed (Revision Needed) ─────────► [Loop back to Matcher (max 2 retries)]
```

### 1. Ingestion Agent
Takes unstructured text (SMS or web form) and extracts a structured schema: need type (medical, water, food, shelter, rescue), quantity estimate, and urgency. It passes the extracted location text to Nominatim with LRU caching to get latitude and longitude. If the LLM produces malformed output or goes offline, it automatically falls back to regex pattern extraction so reports never get dropped.

### 2. Verification Agent
Checks if this incoming report is a duplicate of something already reported. It encodes the need into a 384-dimensional vector using `all-MiniLM-L6-v2` and queries a local Qdrant vector database. If a duplicate is detected or if extraction confidence falls below 0.6, it halts the graph and pushes the report directly into the human review queue.

### 3. Human in the Loop Checkpoint
Rather than letting an autonomous system dispatch trucks on low-confidence data, LangGraph pauses the execution thread using persistent SQLite checkpointing. The report appears in the dispatcher dashboard. A human clicks Approve or Reject. Once approved, the exact execution thread resumes where it left off.

### 4. Resource Matcher (Mathematical Allocator)
Takes the verified needs and available depot inventory, and runs an Integer Linear Programming model using `pulp`. The objective function maximizes coverage prioritized by urgency (critical needs get 4x weight) while penalizing travel distance using Haversine formulas. It guarantees zero inventory over-allocation.

### 5. Plan Synthesizer
Turns the solver's raw allocation numbers back into a clear, grounded narrative for field rescue teams. It runs a regex validation pass to ensure the LLM never hallucinates fake depot IDs or need IDs that were not present in the solver's output.

### 6. Evaluator Agent
Acts as an internal senior dispatcher. It evaluates geographic fairness, overall coverage percentage, and unmet critical needs. If critical needs were left unaddressed despite available stock, it sends the plan back to the Matcher with revision notes.

---

## System Architecture

```
┌────────────────────────────────────────────────────────┐
│               React Workstation (Vite)                 │
│  - Tactical Leaflet Live Map                           │
│  - Human Review Queue with Real-time Optimistic State  │
│  - Real-time WebSocket Stream listener (/ws)           │
│  - JWT Authentication (Reviewer vs Admin)              │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP REST / WebSocket (/ws)
┌──────────────────────────▼─────────────────────────────┐
│                 FastAPI Backend                        │
│  - Role-based Access Control (Reviewer / Admin)        │
│  - Real-time WebSocket Manager (ConnectionManager)     │
│  - Sliding-Window Rate Limiter (Redis / FakeRedis)     │
│  - PII Encryption at Rest (Fernet)                     │
│  - Atomic Row-Level Locking (with_for_update)          │
│  - Immutable Plan Audit Trail                          │
│  - Prometheus Observability (/metrics)                 │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
┌──────────────▼────────────┐  ┌──────────▼──────────────┐
│  ARQ / In-Process Worker  │  │  SQLite / PostgreSQL    │
│  - Background execution   │  │  - Report & Needs DB    │
│  - Durable task queue     │  │  - LangGraph State DB   │
└──────────────┬────────────┘  └─────────────────────────┘
               │
┌──────────────▼─────────────────────────────────────────┐
│              LangGraph Coordination Swarm              │
│  - Ingestion, Verification, PuLP Solver, Evaluator     │
│  - Qdrant Vector Search for Deduplication              │
│  - Model Router: Local LM Studio or OpenRouter Cloud   │
└────────────────────────────────────────────────────────┘
```

---

## Security, Observability, and Reliability Highlights

* PII Protection: Reporter contact information is encrypted before it touches the database using `cryptography.fernet` symmetric encryption, keeping personal phone numbers protected at rest.
* Concurrency Protection: Resource inventory decrement uses SQLAlchemy `with_for_update()` row-level locks inside atomic transactions, preventing two parallel dispatches from double-booking the same supplies.
* Audit Logging: Any administrative override of an automated dispatch plan writes an immutable record to `DBPlanAudit` capturing the admin username, timestamp, previous rationale, and new rationale.
* Real-Time Event Fan-Out: The backend exposes a `/ws` WebSocket endpoint managed by `ConnectionManager`. When tasks process, succeed, or require human review, events are broadcast directly to connected dispatch dashboards. In multi-worker deployments, a Redis Pub/Sub bridge coordinates messages across processes.
* Prometheus Metrics: The system exposes application metrics at `/metrics` via `prometheus-fastapi-instrumentator`, tracking total reports submitted, pipeline duration histograms, active WebSocket connections, and dispatcher review actions.
* Flexible Intelligence Tiering: The model router supports running fully offline on local LM Studio (`smollm3-3b`), or connecting to external OpenAI-compatible cloud providers such as OpenRouter running `inclusionai/ling-3.1-flash`.
* Resilient Background Processing: Report submissions enqueue tasks via ARQ. In production with Redis, tasks survive API crashes. In local development without Redis, the engine automatically falls back to in-process async workers so you do not need complex infrastructure just to test.

---

## Tech Stack

* Orchestration: LangGraph with persistent checkpointing
* Optimization: PuLP (Coin-OR CBC solver)
* Backend: FastAPI, SQLAlchemy, Uvicorn, ARQ
* Metrics & Real-Time: Prometheus Client, WebSockets, Redis Pub/Sub
* Vector Database: Qdrant (local embedded mode)
* Embeddings: Sentence Transformers (`all-MiniLM-L6-v2`)
* Security: Bcrypt, PyJWT, Cryptography (Fernet)
* Geocoding: Geopy (Nominatim with LRU cache)
* Frontend: React 19, Vite, Tailwind CSS, Leaflet, Lucide Icons

---

## Quickstart Guide

### Prerequisites
* Python 3.11+
* Node.js 18+
* (Optional) [LM Studio](https://lmstudio.ai/) running locally on port 1234, or an OpenRouter API key

### 1. Clone & Install Dependencies
```bash
# Clone the repository
git clone https://github.com/Harshitmishra001/Multi_Agent_Dispatch_Swarm.git
cd Multi_Agent_Dispatch_Swarm

# Setup Python environment
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux / Mac
pip install -r requirements.txt

# Setup Frontend dependencies
cd frontend
npm install
cd ..
```

### 2. Configure Environment
Create a `.env` file in the project root:
```env
# Database & Auth
DATABASE_URL=sqlite:///./disaster_coordinator.db
JWT_SECRET_KEY=your-secure-jwt-secret-key-here

# Optional: Cloud Strong Model Tier (e.g. OpenRouter)
STRONG_MODEL_API_KEY=your_openrouter_api_key
STRONG_MODEL_BASE_URL=https://openrouter.ai/api/v1
STRONG_MODEL_NAME=inclusionai/ling-3.1-flash

# Optional: Local LM Studio fallback
LM_STUDIO_BASE_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=smollm3-3b
```

### 3. Run Everything (Single Command)
You do not need to juggle separate terminals for FastAPI and React. Run both concurrently with one command from the project root:

```bash
python run.py
```
*(On Windows, you can also simply double-click `start.bat` or run `npm run dev` from the root directory).*

This automatically launches:
* **FastAPI Backend & AI Swarm:** `http://127.0.0.1:8000`
* **Swagger API Documentation:** `http://127.0.0.1:8000/docs`
* **Prometheus Metrics:** `http://127.0.0.1:8000/metrics`
* **WebSocket Channel:** `ws://127.0.0.1:8000/ws`
* **React Tactical Workstation:** `http://localhost:5173`

On first boot, default accounts are seeded automatically:
* Reviewer: `alice` / `reviewer_pass`
* Admin: `admin` / `admin_pass`

Press `Ctrl+C` in your terminal to shut down both backend and frontend servers cleanly.

---

### Alternative: Docker Deployment
If you prefer running containerized services with PostgreSQL and Redis:
```bash
docker compose up --build
```
This spins up 5 containers: FastAPI web process, ARQ background worker, PostgreSQL 15, Redis 7, and a Prometheus monitoring instance at `http://localhost:9090`.

---

## Automated Testing

The project includes an automated test suite covering unit tests, adversarial prompt attacks, solver accuracy, WebSocket streaming, and end-to-end API flows:

```bash
pytest -v
```

All 41 tests pass in around 18 seconds:
* `tests/unit/test_resource_matcher.py`: Validates that the PuLP optimizer respects urgency and capacity constraints.
* `tests/unit/test_model_router.py`: Tests model routing between local LM Studio and cloud providers.
* `tests/unit/test_worker.py`: Verifies ARQ background worker execution and LangGraph streaming.
* `tests/unit/test_verification_agent.py`: Tests deduplication recall with embedding vectors.
* `tests/unit/test_plan_synthesizer.py`: Tests hallucination rejection when unauthorized IDs are produced.
* `tests/unit/test_evaluator_agent.py`: Tests deterministic coverage calculations and fairness evaluation.
* `tests/test_adversarial.py`: Tests prompt injection resistance and conflicting urgent requests.
* `tests/integration/test_graph.py`: Verifies LangGraph human review interrupts and evaluator revision loops.
* `tests/integration/test_api.py`: 16 integration tests verifying auth, PII encryption at rest, rate limiting (429), human approval/rejection endpoints, and admin audit logging.
* `tests/integration/test_phase4.py`: Integration tests for `/metrics` Prometheus scraping and `/ws` WebSocket connection broadcasting.
