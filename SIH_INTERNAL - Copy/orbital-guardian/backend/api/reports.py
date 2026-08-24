"""
Conjunction report generation (ANALYST+).

POST /reports/conjunction/{event_id}  — generate + persist report
GET  /reports/{report_id}             — fetch stored report
GET  /reports/{report_id}/html        — printable HTML document
"""

import html as html_module
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, require_role
from backend.database.connection import get_db
from backend.database.models import Conjunction, Report
from backend.rag.copilot import explain_event_deterministic

router = APIRouter(prefix="/reports", tags=["reports"])


def _esc(value) -> str:
    return html_module.escape(str(value if value is not None else "—"))


def _build_report_content(record: Conjunction, db: Session) -> dict:
    factors = record.risk_factors or {}

    weights = factors.get("weights", {})

    contributions = []

    for label, factor_key, weight_key in [
        ("Miss Distance", "distance_factor", "distance"),
        ("Relative Velocity", "relative_velocity_factor", "relative_velocity"),
        ("Time Urgency", "time_to_tca_factor", "time_to_tca"),
        ("Object Criticality", "object_type_factor", "object_type"),
    ]:
        factor_value = factors.get(factor_key, 0)
        weight = weights.get(weight_key, 0)
        contributions.append({
            "factor": label,
            "earned": round(factor_value * weight * 100),
            "max": round(weight * 100),
        })

    explanation = explain_event_deterministic({
        "minimum_distance_km": record.minimum_distance_km,
        "relative_velocity_km_s": record.relative_velocity_km_s,
        "risk_score": record.risk_score,
        "risk_level": record.risk_status,
        "risk_factors": factors,
    })

    return {
        "event_id": record.id,
        "analysis_time": record.created_at.isoformat()
        if record.created_at else None,
        "objects": {
            "a": {"norad_id": record.satellite_a_norad_id},
            "b": {"norad_id": record.satellite_b_norad_id},
        },
        "tca": record.tca.isoformat(),
        "miss_distance_km": record.minimum_distance_km,
        "coarse_distance_km": record.coarse_distance_km,
        "relative_velocity_km_s": record.relative_velocity_km_s,
        "operational_risk_priority": {
            "score": record.risk_score,
            "level": record.risk_status,
            "contributions": contributions,
            "disclaimer": (
                "Heuristic screening priority — NOT a probability of "
                "collision (Pc). Pc requires covariance data that public "
                "TLEs do not provide."
            ),
        },
        "data_confidence": record.confidence,
        "methodology": (
            "SGP4 propagation of both objects' latest TLEs; broad-phase "
            "sampled-distance screening; ±1 minute fine refinement at "
            "1-second resolution around the coarse TCA; relative velocity "
            "computed from SGP4 velocity vectors at TCA. All steps are "
            "deterministic."
        ),
        "sources": [
            "Orbital elements: CelesTrak (primary) with cache fallbacks",
            "Propagation: sgp4 Python library (reference implementation)",
            "Risk model: Orbital Guardian Operational Risk Priority v1",
        ],
        "explanation": explanation,
    }


@router.post("/conjunction/{event_id}", status_code=201)
def generate_report(
    event_id: int,
    user=Depends(require_role("ANALYST")),
    db: Session = Depends(get_db),
):
    record = db.query(Conjunction).filter(Conjunction.id == event_id).first()

    if record is None:
        raise HTTPException(status_code=404, detail="Conjunction event not found.")

    content = _build_report_content(record, db)

    report = Report(
        conjunction_id=event_id,
        generated_by=user.id,
        content=content,
    )

    db.add(report)
    db.commit()
    db.refresh(report)

    return {"report_id": report.id, "created_at": report.created_at.isoformat()}


@router.get("/{report_id}")
def get_report(
    report_id: int,
    _user=Depends(require_role("VIEWER")),
    db: Session = Depends(get_db),
):
    report = db.query(Report).filter(Report.id == report_id).first()

    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")

    return {"report_id": report.id, "content": report.content}


@router.get("/{report_id}/html", response_class=HTMLResponse)
def report_html(
    report_id: int,
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(Report).filter(Report.id == report_id).first()

    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")

    c = report.content

    rows = "".join(
        f"<tr><td>{_esc(x['factor'])}</td>"
        f"<td>{x['earned']} / {x['max']}</td></tr>"
        for x in c["operational_risk_priority"]["contributions"]
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Orbital Guardian — Conjunction Report OG-C-{_esc(c['event_id'])}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 800px;
         margin: 2rem auto; color: #0b1420; line-height: 1.5; }}
  h1 {{ border-bottom: 3px solid #0e2a47; padding-bottom: .5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #c9d4e0; padding: .5rem .75rem;
            text-align: left; }}
  th {{ background: #0e2a47; color: white; }}
  .meta {{ background: #f0f4f8; padding: 1rem; border-radius: 6px;
           font-size: .95rem; }}
  .disclaimer {{ margin-top: 1.5rem; padding: .75rem 1rem;
                 border-left: 4px solid #b8860b; background: #fdf6e3;
                 font-size: .9rem; }}
</style>
</head>
<body>
<h1>Conjunction Report — OG-C-{_esc(c['event_id'])}</h1>

<div class="meta">
  <strong>Analysis time:</strong> {_esc(c['analysis_time'])}<br>
  <strong>Object A:</strong> NORAD {_esc(c['objects']['a']['norad_id'])}<br>
  <strong>Object B:</strong> NORAD {_esc(c['objects']['b']['norad_id'])}<br>
  <strong>TCA:</strong> {_esc(c['tca'])}<br>
  <strong>Miss distance:</strong> {_esc(round(c['miss_distance_km'], 4))} km<br>
  <strong>Relative velocity:</strong>
    {_esc(round((c['relative_velocity_km_s'] or 0), 3))} km/s<br>
  <strong>Data confidence:</strong> {_esc(c['data_confidence'])}%
</div>

<h2>Operational Risk Priority</h2>
<p><strong>{_esc(c['operational_risk_priority']['score'])} / 100
   ({_esc(c['operational_risk_priority']['level'])})</strong></p>
<table>
  <tr><th>Factor</th><th>Points</th></tr>
  {rows}
</table>

<h2>Methodology</h2>
<p>{_esc(c['methodology'])}</p>

<h2>Deterministic Explanation</h2>
<p>{_esc(c['explanation'])}</p>

<h2>Sources</h2>
<ul>
  {''.join('<li>' + _esc(s) + '</li>' for s in c['sources'])}
</ul>

<div class="disclaimer">
  <strong>Scientific disclaimer:</strong><br>
  {_esc(c['operational_risk_priority']['disclaimer'])}
</div>

<p style="margin-top:2rem;font-size:.8rem;color:#667;">
  Generated by Orbital Guardian · {datetime.now(timezone.utc).isoformat()}
</p>
</body>
</html>"""
