"""
AI Space Intelligence Copilot.

Architecture:

    user question -> context detection -> tool/data retrieval
    (DB / object profile / event data) -> context builder
    -> configured LLM (optional) -> grounded answer

RULES ENFORCED HERE:
- The LLM receives ONLY verified system data as context.
- If no AI provider is configured, a deterministic template
  explainer answers using the same real data. It never invents
  orbital quantities, statuses, or probabilities.
- Every answer includes the data sources used.
"""

import json

import requests

from backend.config import (
    AI_API_KEY,
    AI_BASE_URL,
    AI_MODEL,
    ai_configured,
    ai_provider_kind,
)
from backend.rag.retriever import retrieve


class CopilotResult:
    def __init__(self, answer: str, sources: list[dict], mode: str):
        self.answer = answer
        self.sources = sources
        self.mode = mode  # "llm" | "deterministic"

    def to_dict(self):
        return {"answer": self.answer, "sources": self.sources, "mode": self.mode}


# ==========================================
# CONTEXT BUILDING (from REAL system data)
# ==========================================


def build_event_context(event_data: dict) -> str:
    """Serialize an actual conjunction event for grounding."""

    lines = [
        "VERIFIED EVENT DATA (do not contradict):",
        f"- Event ID: {event_data.get('id')}",
        f"- Object A: {event_data.get('object_a_name')} "
        f"(NORAD {event_data.get('object_a_norad_id')})",
        f"- Object B: {event_data.get('object_b_name')} "
        f"(NORAD {event_data.get('object_b_norad_id')})",
        f"- TCA: {event_data.get('tca')}",
        f"- Miss distance: {event_data.get('minimum_distance_km')} km",
        f"- Relative velocity: {event_data.get('relative_velocity_km_s')} km/s",
        f"- Operational Risk Priority: "
        f"{event_data.get('risk_score')}/100 ({event_data.get('risk_level')})",
        f"- Risk factor breakdown: "
        f"{json.dumps(event_data.get('risk_factors', {}), default=str)}",
        f"- Data confidence: {event_data.get('confidence')}",
    ]

    return "\n".join(lines)


def build_object_context(profile: dict) -> str:
    orbit = profile.get("live_orbit", {})
    quality = profile.get("data_quality", {})

    lines = [
        "VERIFIED OBJECT DATA (do not contradict):",
        f"- Name: {profile['identity']['object_name']}",
        f"- NORAD ID: {profile['identity']['norad_id']}",
        f"- Type: {profile['identity']['object_type']}",
        f"- Operational status: {profile['status']['status']} "
        f"({profile['status']['basis']})",
        f"- Current altitude: {orbit.get('altitude_km')} km",
        f"- Speed: {orbit.get('velocity_km_s')} km/s",
        f"- Inclination: {orbit.get('inclination_deg')} deg",
        f"- Apogee/perigee: {orbit.get('apogee_altitude_km')}/"
        f"{orbit.get('perigee_altitude_km')} km",
        f"- Period: {orbit.get('orbital_period_min')} min",
        f"- TLE age: {quality.get('tle_age_hours')} h "
        f"({quality.get('freshness')})",
        f"- Data confidence: {quality.get('confidence_score')}%",
    ]

    mission = profile.get("mission") or {}

    if mission.get("mission_name"):
        lines.append(f"- Mission: {mission['mission_name']}")
    if mission.get("operator"):
        lines.append(f"- Operator: {mission['operator']}")
    if mission.get("mission_description"):
        lines.append(f"- Mission description: {mission['mission_description']}")
    if mission.get("_debris_context"):
        lines.append(f"- Debris note: {mission['_debris_context']}")

    ctx = profile.get("conjunction_context") or {}

    upcoming = ctx.get("upcoming_events") or []

    if upcoming:
        lines.append(
            f"- Upcoming recorded conjunctions in database: {len(upcoming)}; "
            f"next at {ctx['next_event']['tca']} with "
            f"{ctx['next_event']['minimum_distance_km']:.1f} km separation."
        )
    else:
        lines.append("- No conjunctions involving this object in local database.")

    return "\n".join(lines)


# ==========================================
# DETERMINISTIC EXPLAINER (no AI required)
# ==========================================


def explain_event_deterministic(event_data: dict) -> str:
    """
    Fully rule-based explanation built ONLY from real numbers.
    Used when no LLM is configured — and as the factual skeleton
    for LLM prompts.
    """

    distance = event_data.get("minimum_distance_km") or 0
    velocity = event_data.get("relative_velocity_km_s") or 0
    score = event_data.get("risk_score") or 0
    factors = event_data.get("risk_factors", {}) or {}

    weights = factors.get("weights", {})

    contributions = {
        "miss distance": (
            factors.get("distance_factor", 0),
            weights.get("distance", 0.5),
        ),
        "relative velocity": (
            factors.get("relative_velocity_factor", 0),
            weights.get("relative_velocity", 0.2),
        ),
        "time urgency": (
            factors.get("time_to_tca_factor", 0),
            weights.get("time_to_tca", 0.2),
        ),
        "object criticality": (
            factors.get("object_type_factor", 0),
            weights.get("object_type", 0.1),
        ),
    }

    top_factor = max(contributions, key=lambda k: contributions[k][0] * contributions[k][1])

    dominant = max(contributions.values(), key=lambda pair: pair[0] * pair[1])[0]

    level = event_data.get("risk_level", "UNKNOWN")

    parts = [
        f"This event is ranked {level} priority with an Operational Risk "
        f"Priority of {score}/100.",
        f"The predicted minimum separation is {distance:.2f} km and the "
        f"relative velocity at closest approach is {velocity:.1f} km/s "
        f"(a typical LEO crossing speed).",
    ]

    if top_factor == "miss distance":
        parts.append(
            "The ranking is driven primarily by the small predicted miss "
            "distance between the two objects."
        )
    elif top_factor == "relative velocity":
        parts.append(
            "The high closing velocity contributes strongly to the ranking, "
            "because fast encounters leave less margin for uncertainty."
        )
    elif top_factor == "time urgency":
        parts.append(
            "The encounter is imminent within the forecast horizon, which "
            "raises its operational urgency."
        )
    else:
        parts.append(
            "Object classification contributes notably: inert objects such "
            "as debris or rocket bodies raise attention because they cannot "
            "maneuver."
        )

    parts.append(
        "Important limitations: this score prioritizes attention; it is NOT "
        "a probability of collision. Public TLE data carries positional "
        "uncertainty that grows after epoch, so computed values are "
        "approximate. A close predicted approach does not mean a collision "
        "will occur."
    )

    return " ".join(parts)


def explain_object_deterministic(profile: dict) -> str:
    identity = profile["identity"]
    quality = profile.get("data_quality", {})
    status = profile.get("status", {})

    mission = profile.get("mission") or {}

    parts = [
        f"{identity['object_name']} (NORAD {identity['norad_id']}) is tracked "
        f"as a {identity.get('object_type', 'UNKNOWN').lower()}."
    ]

    if mission.get("mission_name"):
        parts.append(f"It belongs to the {mission['mission_name']} mission.")

    if mission.get("mission_description"):
        parts.append(mission["mission_description"])

    if mission.get("_debris_context"):
        parts.append(mission["_debris_context"])

    parts.append(f"Operational status: {status.get('status', 'UNKNOWN')} "
                 f"— basis: {status.get('basis', 'unknown')}.")

    orbit = profile.get("live_orbit", {})

    parts.append(
        f"Currently at roughly {orbit.get('altitude_km')} km altitude, "
        f"inclination {orbit.get('inclination_deg')} degrees, orbital period "
        f"about {orbit.get('orbital_period_min')} minutes."
    )

    parts.append(
        f"Orbital data is {quality.get('freshness')} "
        f"({quality.get('tle_age_hours')} h old); prediction confidence is "
        f"{quality.get('confidence_score')}%."
    )

    return " ".join(parts)


# ==========================================
# LLM CALL (only when configured)
# ==========================================

SYSTEM_PROMPT = """You are Orbital Guardian's Space Intelligence Copilot.
You explain satellite conjunction analysis to operators.

STRICT RULES:
- Use ONLY the VERIFIED SYSTEM DATA provided in the context.
- Never invent positions, velocities, TCAs, distances, statuses or dates.
- Never state that a collision will occur. The risk score is a screening
  priority, not a probability of collision.
- Be concise, technical, and factual. If information is missing, say so."""


def _call_gemini(question: str, context: str) -> str | None:
    """Google Gemini via the Generative Language API."""

    try:
        response = requests.post(
            f"{AI_BASE_URL}/models/{AI_MODEL}:generateContent",
            params={"key": AI_API_KEY},
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {
                    "parts": [{"text": SYSTEM_PROMPT}]
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": f"{context}\n\nUSER QUESTION: {question}"}
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 700,
                },
            },
            timeout=40,
        )

        if response.status_code != 200:
            print(f"[COPILOT] Gemini HTTP {response.status_code}: "
                  f"{response.text[:200]}")
            return None

        payload = response.json()

        candidates = payload.get("candidates") or []

        if not candidates:
            return None

        parts = (candidates[0].get("content") or {}).get("parts") or []

        text = "".join(p.get("text", "") for p in parts).strip()

        return text or None

    except Exception as e:
        print(f"[COPILOT] Gemini call failed: {e}")
        return None


def _call_llm(question: str, context: str) -> str | None:
    if ai_provider_kind == "gemini":
        return _call_gemini(question, context)

    try:
        response = requests.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"{context}\n\nUSER QUESTION: {question}",
                    },
                ],
                "temperature": 0.2,
                "max_tokens": 500,
            },
            timeout=30,
        )

        if response.status_code != 200:
            return None

        return response.json()["choices"][0]["message"]["content"].strip()

    except Exception as e:
        print(f"[COPILOT] LLM call failed: {e}")
        return None


# ==========================================
# PUBLIC ENTRY POINTS
# ==========================================


def answer_question(question: str, object_profile=None, event_data=None,
                    extra_context: str = "") -> CopilotResult:
    """
    Answer a copilot question grounded in system data.

    Priority: real event context > object profile > general knowledge.
    """

    sources = []

    context_parts = []

    if event_data:
        context_parts.append(build_event_context(event_data))
        sources.append({"kind": "conjunction_database_record"})
        context_parts.append(explain_event_deterministic(event_data))

    if object_profile:
        context_parts.append(build_object_context(object_profile))
        sources.append({
            "kind": "object_intelligence_profile",
            "norad_id": object_profile["identity"]["norad_id"],
        })

    kb_hits = retrieve(question)

    for hit in kb_hits:
        context_parts.append(
            f"KNOWLEDGE BASE [{hit['title']}]:\n{hit['excerpt']}"
        )

        sources.append({"kind": "knowledge_base", "document": hit["source"]})

    if extra_context:
        context_parts.append(extra_context)

    context = "\n\n".join(context_parts)

    # General questions with no data and no KB hit still need an answer.
    if not context:
        context = (
            "No specific object or event selected. Answer from the knowledge "
            "base only. Do not invent any live data."
        )

    if ai_configured:
        llm_answer = _call_llm(question, context)

        if llm_answer:
            return CopilotResult(llm_answer, sources, "llm")

    # Deterministic fallback / offline mode.
    if event_data and not kb_hits:
        answer = explain_event_deterministic(event_data)
    elif object_profile and not kb_hits:
        answer = explain_object_deterministic(object_profile)
    elif kb_hits:
        best = kb_hits[0]
        answer = (
            f"From the scientific knowledge base ({best['title']}):\n\n"
            + best["excerpt"]
            + ("\n\n[Configure an AI provider for conversational answers; "
               "this summary comes directly from the bundled reference docs.]"
               if not ai_configured else "")
        )
    else:
        answer = (
            "I can only answer from verified system data and the bundled "
            "knowledge base. Select an object or conjunction event, or ask "
            "about concepts like TLE, SGP4, TCA or miss distance."
        )

    return CopilotResult(answer, sources, "deterministic")
