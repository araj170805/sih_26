"""
Watchlist endpoints (ANALYST+).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.dependencies import require_role
from backend.database.connection import get_db
from backend.database.models import Watchlist as WatchlistRecord
from backend.database.models import WatchlistObject

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


class WatchlistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class WatchlistObjectAdd(BaseModel):
    norad_id: int = Field(..., gt=0)
    name: str | None = Field(None, max_length=120)


def _own_watchlist(watchlist_id: int, user, db: Session) -> WatchlistRecord:
    record = (
        db.query(WatchlistRecord)
        .filter(WatchlistRecord.id == watchlist_id)
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="Watchlist not found.")

    # ADMINs may view all watchlists; users only their own.
    if user.role != "ADMIN" and record.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your watchlist.")

    return record


@router.get("")
def list_watchlists(user=Depends(require_role("VIEWER")), db=Depends(get_db)):
    query = db.query(WatchlistRecord)

    if user.role != "ADMIN":
        query = query.filter(WatchlistRecord.user_id == user.id)

    records = query.order_by(WatchlistRecord.created_at.desc()).all()

    return {
        "watchlists": [
            {
                "id": w.id,
                "name": w.name,
                "objects": [
                    {"norad_id": o.norad_id, "name": o.name}
                    for o in w.objects
                ],
                "created_at": w.created_at.isoformat(),
            }
            for w in records
        ]
    }


@router.post("", status_code=201)
def create_watchlist(
    request: WatchlistCreate,
    user=Depends(require_role("ANALYST")),
    db=Depends(get_db),
):
    record = WatchlistRecord(user_id=user.id, name=request.name.strip())

    db.add(record)
    db.commit()
    db.refresh(record)

    return {"id": record.id, "name": record.name, "objects": []}


@router.delete("/{watchlist_id}", status_code=204)
def delete_watchlist(
    watchlist_id: int,
    user=Depends(require_role("ANALYST")),
    db=Depends(get_db),
):
    record = _own_watchlist(watchlist_id, user, db)

    db.delete(record)
    db.commit()


@router.post("/{watchlist_id}/objects", status_code=201)
def add_object(
    watchlist_id: int,
    request: WatchlistObjectAdd,
    user=Depends(require_role("ANALYST")),
    db=Depends(get_db),
):
    watchlist = _own_watchlist(watchlist_id, user, db)

    existing = (
        db.query(WatchlistObject)
        .filter(
            WatchlistObject.watchlist_id == watchlist_id,
            WatchlistObject.norad_id == request.norad_id,
        )
        .first()
    )

    if existing:
        raise HTTPException(status_code=409, detail="Already on this watchlist.")

    obj = WatchlistObject(
        watchlist_id=watchlist.id,
        norad_id=request.norad_id,
        name=request.name,
    )

    db.add(obj)
    db.commit()

    return {"detail": "Added.", "norad_id": request.norad_id}


@router.delete("/{watchlist_id}/objects/{norad_id}", status_code=204)
def remove_object(
    watchlist_id: int,
    norad_id: int,
    user=Depends(require_role("ANALYST")),
    db=Depends(get_db),
):
    _own_watchlist(watchlist_id, user, db)

    obj = (
        db.query(WatchlistObject)
        .filter(
            WatchlistObject.watchlist_id == watchlist_id,
            WatchlistObject.norad_id == norad_id,
        )
        .first()
    )

    if obj is None:
        raise HTTPException(status_code=404, detail="Object not on watchlist.")

    db.delete(obj)
    db.commit()


@router.get("/{watchlist_id}/conjunctions")
def watchlist_conjunctions(
    watchlist_id: int,
    user=Depends(require_role("VIEWER")),
    db=Depends(get_db),
):
    """Conjunction events involving any watchlisted object."""

    from sqlalchemy import or_  # noqa: PLC0415

    from backend.database.models import Conjunction

    watchlist = _own_watchlist(watchlist_id, user, db)

    norad_ids = [o.norad_id for o in watchlist.objects]

    if not norad_ids:
        return {"events": [], "note": "Watchlist is empty."}

    records = (
        db.query(Conjunction)
        .filter(
            or_(
                Conjunction.satellite_a_norad_id.in_(norad_ids),
                Conjunction.satellite_b_norad_id.in_(norad_ids),
            )
        )
        .order_by(Conjunction.tca.desc())
        .limit(100)
        .all()
    )

    return {
        "events": [
            {
                "id": r.id,
                "object_a_norad_id": r.satellite_a_norad_id,
                "object_b_norad_id": r.satellite_b_norad_id,
                "tca": r.tca.isoformat(),
                "minimum_distance_km": r.minimum_distance_km,
                "risk_status": r.risk_status,
                "risk_score": r.risk_score,
            }
            for r in records
        ]
    }
