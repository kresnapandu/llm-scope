# llmscope SDK

Python SDK for [llm-scope](https://github.com/yourusername/llm-scope) — self-hostable LLM observability.

## Installation

```bash
pip install llmscope
# With all integrations:
pip install "llmscope[all]"
```

## Quick Start

```python
import llmscope
from openai import OpenAI

llmscope.init(
    endpoint="http://localhost:4317",
    service_name="my-app",
)

client = OpenAI()

with llmscope.trace_context(user_id="u_123", feature="chat"):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello!"}],
    )
```

## LangChain Integration

```python
from llmscope.integrations.langchain import LLMScopeCallbackHandler

handler = LLMScopeCallbackHandler(judge_faithfulness=True)
chain.invoke({"input": "..."}, config={"callbacks": [handler]})
```

## FastAPI Integration

```python
from fastapi import FastAPI
from llmscope.integrations.fastapi import LLMScopeMiddleware

app = FastAPI()
app.add_middleware(
    LLMScopeMiddleware,
    user_id_extractor=lambda req: req.headers.get("X-User-Id"),
)
```
