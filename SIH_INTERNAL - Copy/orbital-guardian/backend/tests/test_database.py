from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from backend.database.connection import SessionLocal, engine
from backend.database.models import Conjunction, Forecast, Satellite

# ==========================================
# FIXTURES
# ==========================================

TEST_NORAD = 99999


@pytest.fixture
def db_session():

    session = SessionLocal()

    yield session

    # Cleanup any test rows
    session.query(Conjunction).filter(
        Conjunction.satellite_a_norad_id == TEST_NORAD
    ).delete()

    session.query(Conjunction).filter(
        Conjunction.satellite_b_norad_id == TEST_NORAD
    ).delete()

    session.query(Forecast).filter(
        Forecast.start_time >= datetime(2020, 1, 1),
        Forecast.start_time <= datetime(2020, 1, 2),
    ).delete()

    session.query(Satellite).filter(Satellite.norad_id == TEST_NORAD).delete()

    session.commit()
    session.close()


# ==========================================
# 1. DATABASE CONNECTION
# ==========================================


def test_database_connection():

    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))

        assert result.scalar() == 1


def test_tables_exist():
    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    for table in ("satellites", "forecasts", "conjunctions"):
        assert table in existing_tables, f"Table {table} missing"


# ==========================================
# 2. SATELLITE INSERTION
# ==========================================


def test_satellite_insertion(db_session):

    record = Satellite(norad_id=TEST_NORAD, name="TEST SAT")

    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    assert record.id is not None
    assert record.norad_id == TEST_NORAD
    assert record.created_at is not None

    fetched = (
        db_session.query(Satellite).filter(Satellite.norad_id == TEST_NORAD).first()
    )

    assert fetched.name == "TEST SAT"


def test_satellite_norad_unique(db_session):

    db_session.add(Satellite(norad_id=TEST_NORAD, name="A"))
    db_session.commit()

    duplicate = Satellite(norad_id=TEST_NORAD, name="B")

    db_session.add(duplicate)

    with pytest.raises(Exception):
        db_session.commit()

    db_session.rollback()


# ==========================================
# 3. FORECAST INSERTION
# ==========================================


def test_forecast_insertion(db_session):

    start = datetime(2020, 1, 1, tzinfo=timezone.utc)

    record = Forecast(start_time=start, horizon_hours=24, step_minutes=1)

    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    assert record.id is not None
    assert record.horizon_hours == 24
    assert record.user_id is None


# ==========================================
# 4. CONJUNCTION INSERTION
# ==========================================


def test_conjunction_insertion(db_session):

    start = datetime(2020, 1, 1, tzinfo=timezone.utc)

    forecast = Forecast(start_time=start, horizon_hours=24, step_minutes=1)

    db_session.add(forecast)
    db_session.commit()

    conjunction = Conjunction(
        forecast_id=forecast.id,
        satellite_a_norad_id=TEST_NORAD,
        satellite_b_norad_id=25544,
        tca=start + timedelta(hours=5),
        minimum_distance_km=42.5,
        coarse_tca=start + timedelta(hours=5, minutes=-1),
        coarse_distance_km=43.2,
        risk_status="MONITOR",
        refined=True,
    )

    db_session.add(conjunction)
    db_session.commit()
    db_session.refresh(conjunction)

    assert conjunction.id is not None
    assert conjunction.forecast_id == forecast.id
    assert conjunction.risk_status == "MONITOR"

    # Relationship check
    assert conjunction.forecast.id == forecast.id
