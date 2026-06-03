"""
Custom OTLP exporter helpers for llm-scope.
Provides a convenience function to create a pre-configured exporter.
"""

from __future__ import annotations

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def make_otlp_exporter(endpoint: str, insecure: bool = True) -> OTLPSpanExporter:
    """
    Create an OTLP gRPC span exporter.

    Args:
        endpoint: gRPC endpoint URL (e.g. "http://localhost:4317").
        insecure: If True, skip TLS verification (suitable for local dev).

    Returns:
        Configured OTLPSpanExporter instance.
    """
    return OTLPSpanExporter(endpoint=endpoint, insecure=insecure)


def make_console_exporter() -> ConsoleSpanExporter:
    """Create a console span exporter for debugging."""
    return ConsoleSpanExporter()
