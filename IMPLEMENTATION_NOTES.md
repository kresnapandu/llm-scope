# Implementation Notes — llm-scope v0.1.0

## Keputusan Implementasi

### SDK

**`config.py` dipisahkan dari `core.py`**
Spesifikasi menyebut `_config` dict di `core.py`, tapi ini menyebabkan circular import karena interceptors perlu import config, sementara core perlu import interceptors. Solusi: `_config` dan `calculate_cost` dipindah ke `sdk/llmscope/config.py` terpisah. Semua module import dari sana.

**Streaming wrapper menggunakan generator biasa, bukan `MessageStreamManager`**
Anthropic's `MessageStreamManager` memiliki API yang berubah antar versi. Implementasi ini mewrap iterator event stream mentah yang lebih stabil. Untuk streaming Anthropic, interceptor menangani context manager (`__enter__`/`__exit__`) dan iterator biasa.

**`wrapt.wrap_function_wrapper` sebagai mekanisme patch**
Lebih robust dibanding mengganti method secara langsung karena `wrapt` menangani bound methods, staticmethods, dan thread safety. `unpatch()` merestore pointer function original secara manual karena `wrapt` tidak menyediakan built-in unpatch.

**`@traced` decorator mendukung async dan sync**
Implementasi menggunakan `inspect.iscoroutinefunction` untuk generate wrapper yang tepat, sehingga satu decorator bekerja di kedua konteks tanpa kode duplikat.

### Backend

**`judge.py` di-mount langsung di `main.py` sebagai APIRouter**
Spesifikasi menggambarkan judge sebagai service terpisah, tapi untuk simplicity v0.1.0 ini dimasukkan sebagai router FastAPI biasa. Di production bisa dipisah menjadi microservice dengan `uvicorn` terpisah dan hanya membutuhkan perubahan `judge_endpoint` di SDK config.

**SQLAlchemy async dengan `asyncpg`**
Backend menggunakan SQLAlchemy 2.0 async API dengan `asyncpg` driver untuk PostgreSQL. Untuk testing digunakan `aiosqlite` sebagai pengganti sehingga test tidak membutuhkan Postgres real.

**Metrics aggregation menggunakan APScheduler, bukan Celery**
Celery terlalu berat untuk v0.1.0. APScheduler embedded di proses backend lebih simple dan tidak membutuhkan worker terpisah. Tradeoff: tidak bisa scale horizontal tanpa distributed lock.

**OTLP receiver embedded di backend (port 4317)**
Daripada menjalankan OpenTelemetry Collector terpisah sebagai mandatory dependency, collector.py mengimplementasikan OTLP gRPC receiver langsung di backend. `otel-config.yaml` tetap disediakan untuk deployment yang ingin menggunakan OTel Collector sebagai sidecar.

### Dashboard

**Tailwind via CDN bukan PostCSS build**
Karena tidak ada Tailwind compiler setup, dashboard menggunakan Tailwind CDN di `index.html`. Ini berarti semua utility class tersedia tapi ukuran bundle lebih besar. Untuk production, migrate ke PostCSS pipeline.

**`@tanstack/react-query` untuk data fetching**
Menggantikan `useEffect + fetch` manual. React Query menangani caching, refetch, loading states, dan error handling dengan konsisten. `refetchInterval: 10_000` untuk auto-refresh traces.

**Waterfall diagram menggunakan CSS positioning murni**
Daripada library gantt chart yang berat, waterfall menggunakan `position: absolute` dan `width` percentage berdasarkan duration ratio. Simple, performant, dan tidak ada dependency tambahan.

## Hal yang Disederhanakan dari Spesifikasi

**`sentence-transformers` tidak digunakan di judge**
`sentence-transformers` membutuhkan PyTorch (~1GB) yang terlalu berat untuk default installation. Digantikan dengan TF-IDF + cosine similarity menggunakan Python standard library saja. Akurasi sedikit lebih rendah tapi jauh lebih ringan. Untuk production dengan kebutuhan akurasi tinggi, tambahkan `sentence-transformers` sebagai optional dependency.

**Alembic migration files tidak dibuat**
`alembic/versions/` direktori dibuat kosong. `Base.metadata.create_all()` dipanggil di startup lifespan sebagai gantinya. Untuk production, generate migration pertama dengan `alembic revision --autogenerate -m "initial"`.

**Alert notification testing tidak diimplementasikan**
`_send_alert()` di `collector.py` melakukan HTTP POST ke Slack/webhook tapi tidak ada retry logic atau dead letter queue. Di production, gunakan message queue (Redis Pub/Sub atau Celery) untuk reliability.

**Dashboard tidak ada authentication**
v0.1.0 tidak memiliki user auth. Untuk deployment production, tambahkan reverse proxy (nginx/Caddy) dengan basic auth atau integrasikan OAuth2.

**Trace detail view (waterfall full screen) tidak diimplementasikan**
Spesifikasi menyebut route `/traces/:traceId` untuk detail view. Di implementasi ini, waterfall muncul sebagai inline expand di tabel, bukan halaman terpisah. Lebih pragmatis untuk v0.1.0.

## Known Limitations v0.1.0

1. **Tidak ada distributed tracing correlation** — Kalau ada 2 service berbeda yang saling memanggil, trace mereka tidak otomatis terhubung tanpa W3C TraceContext propagation.

2. **Streaming token counting kasar** — Untuk streaming response yang tidak menyertakan usage di chunk terakhir, token count diestimasi dengan word count × 4/3. Bisa error ±20%.

3. **Metrics aggregation eventual consistency** — `metrics_hourly` diaggregasi per jam, jadi summary dashboard mungkin tertinggal hingga 1 jam untuk data terbaru.

4. **OTLP receiver tidak memiliki authentication** — Port 4317 menerima span dari siapa saja. Untuk production, tambahkan mTLS atau network policy.

5. **judge `_judge_async` di LangChain handler** — Kalau event loop tidak berjalan (synchronous context), judge tidak akan dieksekusi. Ini edge case tapi perlu dihandle lebih baik.

## Saran Improvement untuk Versi Berikutnya

**v0.2.0**
- Tambahkan W3C TraceContext propagation untuk distributed tracing antar service
- Implement proper Alembic migrations dengan versioning
- Tambahkan authentication (JWT atau API key) di backend
- Retry logic untuk alert notifications

**v0.3.0**
- Tambahkan `sentence-transformers` sebagai optional judge backend
- Real-time streaming ke dashboard via WebSocket atau SSE
- Trace comparison view (A/B testing)
- Cost forecasting berdasarkan trend historis

**v1.0.0**
- Multi-tenancy support
- Role-based access control
- Data retention policies dengan auto-cleanup
- Export ke Grafana/DataDog sebagai data source
- OpenTelemetry semantic convention compliance audit
