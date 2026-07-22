"""
pool.py — capped, read-only-by-default database access for the Research Engine.

Isolation guarantees implemented here:

  1. HARD CONNECTION CAP. Pools are created with max_size <= 5 (enforced in
     settings.validate()). Research must never exhaust the connections the
     collector and Phantom V2 depend on.

  2. READ-ONLY BY DEFAULT. `fetch()`/`fetchrow()`/`fetchval()` open every
     transaction as READ ONLY, so an accidental INSERT/UPDATE/DELETE against
     raw or operational tables raises instead of corrupting data. Writes are
     only possible through `execute_write()`, which is restricted to the
     `research` schema.

  3. STATEMENT TIMEOUT. Every session sets statement_timeout, so a runaway
     research query cannot pin a backend indefinitely.

  4. FAIL-SOFT. Any failure raises inside the research process only; nothing
     here can affect Phantom V2 or the collector, which run in other processes.
"""

import logging
import asyncpg

from app.config.settings import settings

logger = logging.getLogger("research.db")

# Tables the research engine is allowed to write. Anything else is refused
# before the query ever reaches the database (defence in depth alongside the
# database-level GRANTs).
_WRITE_SCHEMA = "research"


class ResearchPool:
    """One capped asyncpg pool. Read-only unless explicitly writing to research.*"""

    def __init__(self, dsn: str, name: str, read_only: bool = True):
        self.dsn = dsn
        self.name = name
        self.read_only = read_only
        self._pool = None

    async def connect(self):
        if self._pool is not None:
            return self._pool
        if not self.dsn:
            raise RuntimeError(f"[{self.name}] DSN is not configured")

        async def _init(conn):
            await conn.execute(f"SET statement_timeout = {settings.statement_timeout_ms}")
            await conn.execute("SET idle_in_transaction_session_timeout = 30000")

        self._pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=settings.pool_min,
            max_size=settings.pool_max,
            timeout=settings.connect_timeout_s,
            command_timeout=settings.statement_timeout_ms / 1000.0,
            max_inactive_connection_lifetime=30.0,
            statement_cache_size=0,   # safe with poolers (Neon/PgBouncer)
            init=_init,
        )
        logger.info(
            "[%s] pool ready (max %d connections, read_only=%s)",
            self.name, settings.pool_max, self.read_only,
        )
        return self._pool

    async def close(self):
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ── Read paths (always READ ONLY transactions) ───────────────────────────
    async def fetch(self, query: str, *args):
        pool = await self.connect()
        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        pool = await self.connect()
        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        pool = await self.connect()
        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                return await conn.fetchval(query, *args)

    # ── Write path (research schema only) ────────────────────────────────────
    async def execute_write(self, query: str, *args):
        """Write to research.* only. Refuses anything else before execution."""
        if self.read_only:
            raise PermissionError(
                f"[{self.name}] is a read-only pool; writes are not permitted"
            )
        lowered = " ".join(query.lower().split())
        if _WRITE_SCHEMA not in lowered:
            raise PermissionError(
                "Research writes must target the 'research' schema. "
                f"Refused query: {query[:120]}"
            )
        pool = await self.connect()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def execute_write_many(self, query: str, rows):
        """Batched write to research.* only (one round-trip for many rows).
        Same schema guard as execute_write. Refuses non-research writes."""
        if self.read_only:
            raise PermissionError(
                f"[{self.name}] is a read-only pool; writes are not permitted"
            )
        lowered = " ".join(query.lower().split())
        if _WRITE_SCHEMA not in lowered:
            raise PermissionError(
                "Research writes must target the 'research' schema. "
                f"Refused query: {query[:120]}"
            )
        rows = list(rows)
        if not rows:
            return
        pool = await self.connect()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(query, rows)

    async def execute_migration(self, sql: str):
        """Run a migration script (research schema DDL). Explicit and separate."""
        if self.read_only:
            raise PermissionError(f"[{self.name}] is read-only; migrations not permitted")
        pool = await self.connect()
        async with pool.acquire() as conn:
            return await conn.execute(sql)


# Module-level pools — created lazily, shared across the service.
research_ro = ResearchPool(settings.research_db_url, "research_ro", read_only=True)
phantom_ro = ResearchPool(settings.phantom_db_url, "phantom_ro", read_only=True)
research_rw = ResearchPool(settings.research_rw_url, "research_rw", read_only=False)


async def close_all():
    for p in (research_ro, phantom_ro, research_rw):
        try:
            await p.close()
        except Exception as e:   # never propagate shutdown errors
            logger.warning("closing %s failed: %s", p.name, e)
