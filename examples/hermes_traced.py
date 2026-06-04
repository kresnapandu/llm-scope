"""
Wrapper untuk menjalankan Hermes Agent dengan llmscope observability.
Semua LLM call dari Hermes (OpenAI + Anthropic) otomatis ter-trace.

Usage:
    python hermes_traced.py

Pastikan llm-scope stack sudah running:
    make up  (di folder llm-scope)
"""

import llmscope

# Init llmscope SEBELUM Hermes start — ini yang membuat monkey-patch bekerja
llmscope.init(
    endpoint="http://localhost:4317",   # llm-scope collector
    service_name="hermes",              # nama yang muncul di dashboard
    sample_rate=1.0,                    # trace semua call (turunkan ke 0.1 di production)
    judge_sample_rate=0.1,              # 10% completion di-judge halusinasinya
)

print("✅ llmscope aktif — buka http://localhost:3000 untuk lihat traces")
print("🔭 Semua LLM call Hermes akan otomatis ter-record\n")

# Jalankan Hermes seperti biasa
from hermes_cli.main import main
main()
