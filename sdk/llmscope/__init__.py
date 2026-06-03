"""
llm-scope: Self-hostable LLM observability SDK.
Usage:
    import llmscope
    llmscope.init(endpoint="http://localhost:4317", service_name="my-app")
"""

from .core import init, shutdown
from .context import trace_context, traced
from .interceptors import start_span

__all__ = ["init", "shutdown", "trace_context", "traced", "start_span"]
__version__ = "0.1.0"
