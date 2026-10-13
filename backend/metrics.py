"""
Prometheus metrics definitions and registry for the Disaster Coordinator.

All application-level counters and histograms are defined here so every module
can import them without circular dependencies.
"""

from prometheus_client import Counter, Histogram, Gauge

# ── HTTP / pipeline ───────────────────────────────────────────────────────────
REPORTS_SUBMITTED = Counter(
    "dc_reports_submitted_total",
    "Total disaster reports submitted through the /reports endpoint",
)

REPORTS_PROCESSED = Counter(
    "dc_reports_processed_total",
    "Total reports that completed the full LangGraph pipeline",
    labelnames=["status"],   # success | error
)

PIPELINE_LATENCY = Histogram(
    "dc_pipeline_duration_seconds",
    "End-to-end duration of a single report through the LangGraph pipeline",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# ── LLM ───────────────────────────────────────────────────────────────────────
LLM_REQUESTS = Counter(
    "dc_llm_requests_total",
    "Total LLM API calls made",
    labelnames=["tier", "status"],   # tier: local|strong  status: success|rate_limit|error
)

LLM_FALLBACKS = Counter(
    "dc_llm_fallbacks_total",
    "Times the evaluator fell back to the heuristic because the LLM was unavailable",
)

# ── Human review ──────────────────────────────────────────────────────────────
REVIEW_QUEUE_SIZE = Gauge(
    "dc_review_queue_size",
    "Current number of needs sitting in the human-review queue",
)

REVIEW_ACTIONS = Counter(
    "dc_review_actions_total",
    "Human review approve/reject decisions",
    labelnames=["action"],   # approve | reject
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_HITS = Counter(
    "dc_rate_limit_hits_total",
    "Number of requests rejected by the per-IP rate limiter",
)

# ── WebSocket connections ─────────────────────────────────────────────────────
WEBSOCKET_CONNECTIONS = Gauge(
    "dc_websocket_connections_active",
    "Number of currently connected WebSocket clients",
)
