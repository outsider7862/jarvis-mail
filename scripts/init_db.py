"""
Quick-start table creation for local dev / early pilot.

This uses SQLAlchemy's create_all, which is fine while the schema is moving fast.
Once the schema stabilizes, switch to Alembic migrations (already in requirements.txt)
so you can evolve the schema without dropping data.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models import Base
from app.db.session import engine


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created.")


if __name__ == "__main__":
    asyncio.run(init_models())
