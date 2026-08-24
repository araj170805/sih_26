import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# ==========================================
# ENVIRONMENT
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

Base = declarative_base()

def _create_db_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        db_url = "sqlite:///./orbital_guardian.db"

    if db_url.startswith("sqlite"):
        return create_engine(db_url, connect_args={"check_same_thread": False})

    try:
        eng = create_engine(db_url, pool_pre_ping=True)
        with eng.connect() as conn:
            pass
        return eng
    except Exception as e:
        print(f"[DATABASE] Primary DB ({db_url}) unreachable ({e}). Falling back to SQLite.")
        sqlite_url = f"sqlite:///{BASE_DIR / 'orbital_guardian.db'}"
        return create_engine(sqlite_url, connect_args={"check_same_thread": False})

engine = _create_db_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    from backend.database import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

# Auto-create tables on startup
try:
    init_db()
except Exception as _e:
    pass



# ==========================================
# FASTAPI DEPENDENCY
# ==========================================


def get_db():

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()
