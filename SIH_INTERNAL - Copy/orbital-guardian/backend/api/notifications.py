"""
In-app notification endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, require_user
from backend.database.connection import get_db
from backend.database.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    limit: int = Query(20, gt=0, le=100),
    unread_only: bool = Query(False),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    User's notifications plus system-wide broadcasts.
    Unauthenticated callers see only system broadcasts.
    """

    query = db.query(Notification)

    if user:
        from sqlalchemy import or_

        query = query.filter(
            or_(Notification.user_id == user.id, Notification.user_id.is_(None))
        )
    else:
        query = query.filter(Notification.user_id.is_(None))

    if unread_only:
        query = query.filter(Notification.read.is_(False))

    try:
        records = query.order_by(Notification.created_at.desc()).limit(limit).all()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable. Notifications cannot be retrieved.",
        ) from e

    unread = 0

    if user:
        from sqlalchemy import or_ as _or

        unread = (
            db.query(Notification)
            .filter(
                _or(
                    Notification.user_id == user.id,
                    Notification.user_id.is_(None),
                ),
                Notification.read.is_(False),
            )
            .count()
        )

    return {
        "unread_count": unread,
        "notifications": [
            {
                "id": n.id,
                "category": n.category,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "read": n.read,
                "created_at": n.created_at.isoformat(),
            }
            for n in records
        ],
    }


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    user=Depends(require_user),
    db: Session = Depends(get_db),
):
    record = (
        db.query(Notification).filter(Notification.id == notification_id).first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="Notification not found.")

    if record.user_id is not None and record.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your notification.")

    record.read = True
    db.commit()

    return {"detail": "Marked read."}


@router.post("/read-all")
def mark_all_read(user=Depends(require_user), db: Session = Depends(get_db)):
    from backend.database.connection import engine
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE notifications SET read = TRUE "
                "WHERE user_id = :uid OR user_id IS NULL"
            ),
            {"uid": user.id},
        )

    return {"detail": "All marked read."}
