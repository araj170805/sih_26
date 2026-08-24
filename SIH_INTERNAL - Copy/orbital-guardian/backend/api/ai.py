"""
AI Copilot endpoints.

POST /ai/chat           — context-aware Q&A (object/event aware)
POST /ai/explain-event  — explainable breakdown of one conjunction event

Without an AI key both endpoints answer deterministically from real
data + the bundled knowledge base. Nothing is ever invented.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import ai_configured
from backend.database.connection import get_db
from backend.database.models import Conjunction
from backend.intelligence.object_profile import build_object_profile
from backend.rag.copilot import answer_question
from backend.rag.retriever import retrieve

router = APIRouter(prefix="/ai", tags=["ai"])


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    norad_id: int | None = Field(None, description="Selected object context")
    conjunction_id: int | None = Field(None, description="Selected event context")


class ExplainRequest(BaseModel):
    conjunction_id: int


def _event_payload(record: Conjunction) -> dict:
    factors = record.risk_factors or {}

    weights = factors.get("weights", {})

    contributions = {
        "miss distance": factors.get("distance_factor", 0) * weights.get("distance", .5),
        "relative velocity": (
            factors.get("relative_velocity_factor", 0)
            * weights.get("relative_velocity", .2)
        ),
        "time urgency": (
            factors.get("time_to_tca_factor", 0) * weights.get("time_to_tca", .2)
        ),
        "object criticality": (
            factors.get("object_type_factor", 0) * weights.get("object_type", .1)
        ),
    }

    dominant = max(contributions, key=contributions.get)

    return {
        "id": record.id,
        "object_a_norad_id": record.satellite_a_norad_id,
        "object_b_norad_id": record.satellite_b_norad_id,
        "tca": record.tca.isoformat(),
        "minimum_distance_km": record.minimum_distance_km,
        "relative_velocity_km_s": record.relative_velocity_km_s,
        "risk_score": record.risk_score,
        "risk_level": record.risk_status,
        "confidence": record.confidence,
        "dominant_factor": dominant,
        "risk_factors": factors,
    }


@router.post("/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db)):
    object_profile = None
    event_data = None

    if request.conjunction_id:
        record = (
            db.query(Conjunction)
            .filter(Conjunction.id == request.conjunction_id)
            .first()
        )

        if record is None:
            raise HTTPException(status_code=404, detail="Event not found.")

        event_data = _event_payload(record)

    if request.norad_id:
        try:
            object_profile = build_object_profile(request.norad_id, db=db)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"No TLE data found for NORAD {request.norad_id}.",
            )
        except (RuntimeError, ValueError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    result = answer_question(
        request.question,
        object_profile=object_profile,
        event_data=event_data,
    )

    return {
        "provider_configured": ai_configured,
        **result.to_dict(),
    }


@router.post("/explain-event")
def explain_event(request: ExplainRequest, db: Session = Depends(get_db)):
    record = (
        db.query(Conjunction).filter(Conjunction.id == request.conjunction_id).first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="Event not found.")

    event_data = _event_payload(record)

    result = answer_question(
        "Explain this conjunction event simply: why was it flagged, which "
        "factor contributes most to the risk, what do the numbers mean, and "
        "what are the limitations of this prediction?",
        event_data=event_data,
    )

    return {
        "provider_configured": ai_configured,
        **result.to_dict(),
    }


@router.get("/knowledge")
def knowledge(query: str):
    """Direct access to the RAG corpus (deterministic retrieval)."""

    hits = retrieve(query, top_k=5)

    return {"query": query, "results": hits}
