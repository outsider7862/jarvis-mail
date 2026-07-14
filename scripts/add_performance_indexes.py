"""
Adds indexes for the hot query paths (everything is scoped to user_id) that were
missing since day one — every list/filter/notification query was doing a full
table scan. create_all() only creates missing tables, not indexes on existing
ones, so this applies them directly with IF NOT EXISTS (safe to re-run, no data
loss). Mirrors the indexes declared in app/db/models.py.
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import engine

STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_email_analyses_user_created ON email_analyses (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_email_analyses_user_notify ON email_analyses (user_id, should_notify, notified_at)",
    "CREATE INDEX IF NOT EXISTS ix_leads_user_created ON leads (user_id, created_at)",
]


async def add_indexes() -> None:
    async with engine.begin() as conn:
        for statement in STATEMENTS:
            await conn.execute(text(statement))
    print(f"Applied {len(STATEMENTS)} index(es).")


if __name__ == "__main__":
    asyncio.run(add_indexes())
