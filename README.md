# 🔭 llm-scope

[![CI](https://github.com/yourusername/llm-scope/actions/workflows/ci.yml/badge.svg)](https://github.com/yourusername/llm-scope/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/llmscope)](https://pypi.org/project/llmscope/)
[![Python](https://img.shields.io/pypi/pyversions/llmscope)](https://pypi.org/project/llmscope/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Self-hostable LLM observability — from one line of code to a full dashboard.**

![Dashboard](docs/screenshot.png)

---

## Features

- 🔍 **Automatic tracing** — one-line init patches OpenAI and Anthropic clients, no code changes needed
- 💰 **Cost tracking** — real-time cost per call, per user, per feature with model-specific pricing
- ⚠️ **Hallucination scoring** — 3-step pipeline (deterministic → TF-IDF → LLM-as-judge) on a sample of completions
- 🔗 **LangChain integration** — traces chains, LLMs, retrievers, and tools as a native callback handler
- 🌐 **FastAPI middleware** — auto-injects user_id and session context from HTTP headers
- 🔔 **Smart alerting** — configurable rules for cost spikes, error rate, and hallucination score via Slack or webhook
- 📊 **Live dashboard** — waterfall traces, cost charts, hallucination monitor, user leaderboard
- 🐳 **Self-hostable** — one `make up` command to run everything with Docker Compose

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
