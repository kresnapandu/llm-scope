"""
Wrapper untuk menjalankan Hermes Agent dengan llmscope observability.
Support trace per-user dari Telegram, Discord, Slack, dll.

Semua LLM call dari Hermes (OpenAI + Anthropic) otomatis ter-trace,
dikelompokkan per user_id sehingga kamu bisa lihat di dashboard:
  - Siapa yang paling banyak pakai
  - Berapa cost per user
  - User mana yang LLM response-nya sering hallusinasi

Usage:
    python hermes_traced.py

Pastikan llm-scope stack sudah running:
    make up  (di folder llm-scope)
"""

import llmscope

llmscope.init(
    endpoint="http://localhost:4317",
    service_name="hermes",
    sample_rate=1.0,
    judge_sample_rate=0.1,
)

print("✅ llmscope aktif — buka http://localhost:3000 untuk lihat traces")
print("👥 Trace per-user aktif — setiap user Telegram ter-track terpisah\n")

# ── Patch Telegram ────────────────────────────────────────────────────────────
#
# Hermes menerima pesan dari Telegram lewat python-telegram-bot.
# Kita wrap Application.process_update supaya setiap pesan masuk
# sudah punya trace_context dengan user_id dari Telegram.

try:
    import functools
    from telegram import Update
    from telegram.ext import Application

    _original_process_update = Application.process_update

    @functools.wraps(_original_process_update)
    async def _traced_process_update(self, update: Update, *args, **kwargs):
        user_id = None
        username = None
        chat_id = None

        if update.effective_user:
            user_id = str(update.effective_user.id)
            username = (
                update.effective_user.username
                or update.effective_user.first_name
                or "unknown"
            )

        if update.effective_chat:
            chat_id = str(update.effective_chat.id)

        with llmscope.trace_context(
            user_id=user_id,
            session_id=chat_id,
            feature="telegram",
            tags={"telegram.username": username or "unknown"},
        ):
            return await _original_process_update(self, update, *args, **kwargs)

    Application.process_update = _traced_process_update
    print("✅ Telegram patch aktif — trace per user_id siap")

except ImportError:
    print("⚠️  python-telegram-bot tidak terinstall, trace per-user Telegram tidak aktif")
    print("   Install dengan: pip install 'hermes-agent[messaging]'")

# ── Patch Discord ─────────────────────────────────────────────────────────────

try:
    import asyncio
    import functools
    import discord

    _original_on_message = None

    class _TracedClient(discord.Client):
        async def on_message(self, message):
            if message.author == self.user:
                return
            with llmscope.trace_context(
                user_id=str(message.author.id),
                session_id=str(message.channel.id),
                feature="discord",
                tags={"discord.username": str(message.author.name)},
            ):
                if _original_on_message:
                    await _original_on_message(message)

    print("✅ Discord patch aktif — trace per user_id siap")

except ImportError:
    pass  # Discord tidak terinstall, skip

# ── Jalankan Hermes ───────────────────────────────────────────────────────────

from hermes_cli.main import main
main()
