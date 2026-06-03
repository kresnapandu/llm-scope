# 🔭 llm-scope

[![CI](https://github.com/yourusername/llm-scope/actions/workflows/ci.yml/badge.svg)](https://github.com/yourusername/llm-scope/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/llmscope)](https://pypi.org/project/llmscope/)
[![Python](https://img.shields.io/pypi/pyversions/llmscope)](https://pypi.org/project/llmscope/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Self-hostable LLM observability — from one line of code to a full dashboard.**

<img width="1465" height="722" alt="Screenshot 2026-06-04 at 02 16 52" src="https://github.com/user-attachments/assets/5a687504-d209-49e9-bbfc-e22847b75c9e" />

---

## Features

- 🔍 **Automatic tracing** — one-line init patches OpenAI and Anthropic clients, no code changes needed
- 💰 **Cost tracking** — real-time cost per call, per user, per feature with model-specific pricing
- ⚠️ **Hallucination detection** — 3-layer scoring pipeline runs automatically on a sample of your completions
- 🔗 **LangChain integration** — traces chains, LLMs, retrievers, and tools as a native callback handler
- 🌐 **FastAPI middleware** — auto-injects user_id and session context from HTTP headers
- 🔔 **Smart alerting** — configurable rules for cost spikes, error rate, and hallucination score via Slack or webhook
- 📊 **Live dashboard** — waterfall traces, cost charts, hallucination monitor, user leaderboard
- 🐳 **Self-hostable** — one `make up` command to run everything with Docker Compose

---

## How Each Feature Works

### 🔍 Automatic Tracing

llm-scope uses Python's `wrapt` library to monkey-patch the OpenAI and Anthropic clients at initialization time. Every call to `client.chat.completions.create()` or `client.messages.create()` is transparently intercepted — you don't change a single line of your existing code.

Each intercepted call becomes an **OpenTelemetry span** carrying:
- Model name, temperature, and request parameters
- Prompt text (redactable via `redact_prompts=True`)
- Completion text (redactable via `redact_completions=True`)
- Token counts (input + output)
- Latency in milliseconds
- Calculated cost in USD
- Any context tags you inject via `trace_context()` (user_id, session_id, feature)

Spans are sent via **OTLP gRPC** to the backend collector on port 4317 — the same open standard used by Datadog, Google Cloud Trace, and AWS X-Ray.

---

### 💰 Cost Tracking

Cost is calculated locally on every span using built-in model pricing tables (no external API call required). The formula is simple:

```
cost = (input_tokens × input_price + output_tokens × output_price) / 1,000,000
```

Built-in prices cover all major OpenAI and Anthropic models. You can override them at init time:

```python
llmscope.init(
    endpoint="...",
    service_name="my-app",
    model_prices={
        "my-fine-tuned-model": {"input": 2.00, "output": 8.00}
    }
)
```

The backend aggregates costs hourly into a `metrics_hourly` table, enabling the dashboard to show cost-over-time charts, top models by spend, top features by spend, and a per-user leaderboard — all without scanning millions of raw span rows on every query.

---

### ⚠️ Hallucination Detection

Hallucination detection is relevant when you use **RAG (Retrieval-Augmented Generation)** — a pattern where your app retrieves documents from a database and passes them to the LLM as context. The question llm-scope answers automatically: *"Did the LLM stay faithful to the documents it was given, or did it make things up?"*

Scoring runs on a configurable sample of completions (default: 10%) through a **3-layer pipeline**, ordered from cheapest to most expensive:

#### Layer 1 — Keyword Overlap (free, < 1ms)

The simplest check: compare the vocabulary of the retrieved documents against the vocabulary of the LLM's completion. Words that appear in the completion but not in the context are potential hallucinations.

```
hallucination_ratio = out_of_context_words / total_meaningful_words

ratio < 0.2  → likely faithful  → score ≈ 0.1  (stop here)
ratio > 0.8  → likely hallucinated → score ≈ 0.85 (stop here)
0.2–0.8      → inconclusive     → proceed to Layer 2
```

This catches the obvious cases for free — no model inference needed.

#### Layer 2 — TF-IDF Cosine Similarity (~10ms, no API)

For ambiguous cases, llm-scope computes the **cosine similarity** between the context and the completion using TF-IDF vectors. This captures semantic overlap beyond exact keyword matching — a completion that paraphrases the context correctly will still score high similarity even if it uses different words.

```
similarity = dot(ctx_vector, completion_vector) / (|ctx| × |completion|)

hallucination_score = 1.0 - similarity

score < 0.2  → faithful    (stop here)
score > 0.7  → hallucinated (stop here)
otherwise    → still ambiguous → proceed to Layer 3
```

Pure Python math, no GPU, no external dependencies.

#### Layer 3 — LLM-as-Judge (~1–2s, uses OpenAI API)

For cases that remain ambiguous after the first two layers, llm-scope sends the context and completion to a small, cheap judge model (default: `gpt-4o-mini`) with a faithfulness evaluation prompt:

> *"Given this CONTEXT and this COMPLETION, is the completion faithful to the context? Reply FAITHFUL or UNFAITHFUL, then explain in one sentence."*

```
FAITHFUL   → score 0.1
UNFAITHFUL → score 0.85
```

Only completions that couldn't be resolved by the first two layers reach this step, keeping API costs minimal.

#### Score Interpretation

| Score | Meaning |
|-------|---------|
| 0.0 – 0.2 | Faithful — completion is well-grounded in context |
| 0.2 – 0.5 | Uncertain — manual review recommended |
| 0.5 – 1.0 | Likely hallucinated — LLM made claims not in context |

All scored spans appear in the **Hallucination Monitor** dashboard with their score, reasoning, full prompt, completion, and retrieved context — so you can review flagged responses and tune your RAG pipeline.

---

### 🔗 LangChain Integration

The `LLMScopeCallbackHandler` implements LangChain's `BaseCallbackHandler` interface, so it plugs into any chain without modifying your chain code. It traces the full execution tree:

- **Chains** — start/end time and nesting hierarchy
- **LLM calls** — model, tokens, cost, latency (same as the OpenAI/Anthropic interceptors)
- **Retrievers** — query, number of documents returned, top relevance score
- **Tools** — name, input, output

Retrieved documents are captured at the retriever step and passed to the hallucination judge when the parent LLM call completes — enabling accurate faithfulness scoring for the entire RAG flow end-to-end.

---

### 🔔 Smart Alerting

Alert rules are configured in the dashboard and evaluated on every incoming batch of spans. Three rule types are supported:

| Type | Triggers when |
|------|--------------|
| `cost_spike` | Total cost in a batch exceeds the threshold (USD) |
| `error_rate` | Fraction of error spans in a batch exceeds the threshold (0–1) |
| `high_hallucination` | Average hallucination score in a batch exceeds the threshold (0–1) |

Notifications are sent via **Slack webhook** and/or a generic **HTTP webhook**, configurable per rule.

---

## Installation

```bash
pip install llmscope-kresnapandu
```

---

## Quick Start (30 seconds)

```bash
git clone https://github.com/yourusername/llm-scope
cd llm-scope
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD at minimum
make up
# Dashboard: http://localhost:3000
# API:       http://localhost:8000
```

---

## SDK Usage

### OpenAI

```python
import llmscope
from openai import OpenAI

llmscope.init(
    endpoint="http://localhost:4317",
    service_name="my-app",
    sample_rate=1.0,
)

client = OpenAI()

with llmscope.trace_context(user_id="u_123", feature="chat"):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello!"}],
    )
# → Trace appears in dashboard within 5 seconds
```

### Anthropic

```python
import llmscope
import anthropic

llmscope.init(endpoint="http://localhost:4317", service_name="my-app")

client = anthropic.Anthropic()

with llmscope.trace_context(user_id="u_456", feature="summarizer"):
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Summarize this text..."}],
    )
```

### LangChain

```python
import llmscope
from llmscope.integrations.langchain import LLMScopeCallbackHandler

llmscope.init(endpoint="http://localhost:4317", service_name="my-app")

handler = LLMScopeCallbackHandler(judge_faithfulness=True)
chain.invoke(
    {"input": "What is the capital of France?"},
    config={"callbacks": [handler]},
)
```

### FastAPI Middleware

```python
from fastapi import FastAPI
from llmscope.integrations.fastapi import LLMScopeMiddleware

app = FastAPI()
app.add_middleware(
    LLMScopeMiddleware,
    user_id_extractor=lambda req: req.headers.get("X-User-Id"),
    session_id_extractor=lambda req: req.headers.get("X-Session-Id"),
)
```

### `@traced` Decorator

```python
from llmscope import traced

@traced(feature="summarizer")
def summarize(user_id: str, text: str) -> str:
    # user_id is auto-injected into all LLM spans inside this function
    response = client.chat.completions.create(...)
    return response.choices[0].message.content
```

---

## Configuration

All parameters for `llmscope.init()`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `endpoint` | `str` | required | OTLP gRPC endpoint (e.g. `http://localhost:4317`) |
| `service_name` | `str` | required | Name of your application |
| `sample_rate` | `float` | `1.0` | Fraction of traces to capture (0.0–1.0) |
| `redact_prompts` | `bool` | `False` | If True, prompt text is not stored in spans |
| `redact_completions` | `bool` | `False` | If True, completion text is not stored in spans |
| `model_prices` | `dict` | built-in | Custom pricing `{model: {input: float, output: float}}` per 1M tokens |
| `judge_sample_rate` | `float` | `0.1` | Fraction of completions sent to hallucination judge |
| `judge_model` | `str` | `gpt-4o-mini` | Model to use for LLM-as-judge |
| `always_sample_errors` | `bool` | `True` | Always capture error spans regardless of `sample_rate` |

---

## Architecture

llm-scope has five components:

**SDK** (`sdk/`) — Python package that monkey-patches OpenAI/Anthropic clients using `wrapt`, emits OpenTelemetry spans via OTLP gRPC, and provides `trace_context` / `@traced` for injecting user metadata.

**Collector** (`collector/`) — Optional OpenTelemetry Collector sidecar for production deployments; batches and forwards spans to the backend.

**Backend** (`backend/`) — FastAPI service that receives spans via OTLP gRPC (port 4317) and serves the REST API (port 8000). Stores data in PostgreSQL, aggregates hourly metrics, checks alert rules.

**Dashboard** (`dashboard/`) — React + Recharts SPA for browsing traces, analyzing cost, monitoring hallucination scores, and configuring alerts.

**Infrastructure** — Docker Compose glues everything together. One `make up` starts all services.

---

## Development Setup

```bash
# Install SDK in dev mode
cd sdk && pip install -e ".[all]"

# Install dashboard dependencies
cd dashboard && npm install

# Start all services with hot reload
make dev

# Run tests
make test

# Apply DB migrations
make migrate
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, branching strategy, PR checklist, and code style.

---

## License

MIT — see [LICENSE](LICENSE).
