from sqlalchemy import text

from . import models  # noqa: F401 — registers tables with Base.metadata
from .connection import Base, engine

# ==========================================
# ADDITIVE MIGRATIONS
#
# create_all() never alters existing tables,
# so columns added in later versions are
# applied explicitly. Every statement is
# additive and idempotent — no data is ever
# dropped or rewritten.
# ==========================================

MIGRATIONS = [
    # v2.0 — conjunction risk intelligence columns
    "ALTER TABLE conjunctions ADD COLUMN IF NOT EXISTS risk_score INTEGER",
    (
        "ALTER TABLE conjunctions ADD COLUMN IF NOT EXISTS "
        "relative_velocity_km_s DOUBLE PRECISION"
    ),
    "ALTER TABLE conjunctions ADD COLUMN IF NOT EXISTS risk_factors JSONB",
    "ALTER TABLE conjunctions ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION",
]


def migrate():
    """Apply idempotent additive migrations."""
    applied = []

    with engine.begin() as conn:
        for statement in MIGRATIONS:
            try:
                conn.execute(text(statement))
                applied.append(statement[:60])
            except Exception as e:
                print(f"[MIGRATE] Skipped: {statement[:60]}... ({e})")

    return applied


def init_db():
    """
    Create any missing tables, then apply
    additive column migrations.

    Safe to run repeatedly: existing tables
    and data are never modified or dropped.
    """

    Base.metadata.create_all(bind=engine)

    return migrate()


if __name__ == "__main__":
    applied = init_db()

    print("Database initialized:")
    print(" - satellites")
    print(" - forecasts")
    print(" - conjunctions")
    print(" - users / refresh_tokens")
    print(" - analysis_jobs / analysis_job_events")
    print(" - watchlists / watchlist_objects")
    print(" - notifications")
    print(" - object_profiles")
    print(" - reports")

    if applied:
        print(f"\nApplied {len(applied)} additive migrations.")
