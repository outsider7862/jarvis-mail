"""
Sets placeholder environment variables BEFORE any `app.*` module is imported.
app.core.config.Settings() runs at import time, so this has to happen here,
at collection time, not inside a fixture — none of these are real credentials.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/test_db")
os.environ.setdefault("COMPOSIO_API_KEY", "placeholder-composio-key")
os.environ.setdefault("COMPOSIO_WEBHOOK_SECRET", "placeholder-webhook-secret")
os.environ.setdefault("OPENAI_API_KEY", "placeholder-openai-key")
os.environ.setdefault("OPENAI_EXTRACTION_MODEL", "gpt-5.5")
os.environ.setdefault("SUPABASE_JWT_SECRET", "placeholder-test-jwt-secret")
os.environ.setdefault("APP_ENV", "test")
