"""
AI Space Intelligence Copilot.

Architecture:

    user question -> context detection -> tool/data retrieval
    (DB / object profile / event data) -> context builder
    -> Gemini LLM -> grounded answer (with deterministic fallback)

RULES ENFORCED HERE:
- The LLM receives verified system data as primary context.
- For general questions, Gemini answers from its space domain knowledge.
- If the AI call fails, a deterministic template answers using real data.
- Never invents orbital quantities, statuses, or probabilities.
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
    Used when no LLM is configured â€” and as the factual skeleton
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
                 f"â€” basis: {status.get('basis', 'unknown')}.")

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
# LLM CALL (Gemini API)
# ==========================================

# System prompt for context-grounded questions (object/event selected)
SYSTEM_PROMPT_GROUNDED = """You are Orbital Guardian's Space Intelligence Copilot.
You explain satellite conjunction analysis and space situational awareness to operators.

RULES:
- Use the VERIFIED SYSTEM DATA provided in the context as your primary source of truth.
- Never contradict the verified system data.
- Never state that a collision will occur. The risk score is a screening
  priority, not a probability of collision.
- Be concise, technical, and factual. Use bullet points when listing multiple points.
- You may use your general space domain knowledge to supplement explanations,
  but always ground your answer in the verified data first."""

# System prompt for general knowledge questions (no object/event selected)
SYSTEM_PROMPT_GENERAL = """You are Orbital Guardian's Space Intelligence Copilot â€” an expert
AI assistant specializing in space situational awareness, orbital mechanics, satellite operations,
conjunction analysis, and space debris.

You help operators and space professionals understand:
- Orbital mechanics (TLE, SGP4, Keplerian elements, orbital maneuvers, delta-v)
- Conjunction analysis (TCA, miss distance, probability of collision, risk assessment)
- Space objects (satellites, debris, rocket bodies, NORAD IDs, object types)
- Space agencies and missions (ISS, Starlink, GPS, weather satellites, military sats)
- Space policy (IADC debris mitigation guidelines, ITU regulations)
- Space weather and its effects on satellites (atmospheric drag, radiation)
- Satellite operations (maneuver planning, station-keeping, deorbit)

RULES:
- Answer clearly, accurately, and helpfully with technical depth appropriate to the question.
- Be concise but complete. Use bullet points or numbered lists when it aids clarity.
- If asked about a specific satellite's CURRENT position or status, tell the user
  to select that object in the Orbital Guardian dashboard for live data.
- Never invent real-time orbital data, live positions, or specific conjunction events.
- If a question is completely outside space/astronomy domain, politely redirect."""


def _call_gemini(question: str, context: str, system_prompt: str) -> str | None:
    """Google Gemini via the Generative Language API."""

    try:
        url = f"{AI_BASE_URL}/models/{AI_MODEL}:generateContent"
        params = {"key": AI_API_KEY}

        user_text = f"{context}\n\nUSER QUESTION: {question}" if context else question

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_text}],
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1024,
            },
        }

        response = requests.post(
            url,
            params=params,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=40,
        )

        if response.status_code != 200:
            print(
                f"[COPILOT] Gemini HTTP {response.status_code}: "
                f"{response.text[:400]}"
            )
            return None

        data = response.json()
        candidates = data.get("candidates") or []

        if not candidates:
            print(f"[COPILOT] Gemini returned no candidates. Response: {data}")
            return None

        finish_reason = candidates[0].get("finishReason", "")
        if finish_reason not in ("STOP", "MAX_TOKENS", ""):
            print(f"[COPILOT] Gemini finish reason: {finish_reason}")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()

        if text:
            print(f"[COPILOT] Gemini answered ({len(text)} chars, model={AI_MODEL})")
        else:
            print("[COPILOT] Gemini returned empty text.")

        return text or None

    except Exception as e:
        print(f"[COPILOT] Gemini call failed: {e}")
        return None


def _call_llm(question: str, context: str, system_prompt: str) -> str | None:
    """Route to the configured LLM provider."""
    if ai_provider_kind == "gemini":
        return _call_gemini(question, context, system_prompt)

    # OpenAI-compatible fallback
    try:
        user_content = f"{context}\n\nUSER QUESTION: {question}" if context else question
        response = requests.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.3,
                "max_tokens": 800,
            },
            timeout=30,
        )

        if response.status_code != 200:
            print(f"[COPILOT] OpenAI-compat HTTP {response.status_code}: {response.text[:200]}")
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
    Answer a copilot question using Gemini AI for ALL question types.

    Strategy:
    1. Build context from real system data (event/object) + knowledge base.
    2. If live system data is present â†’ grounded system prompt.
    3. For general questions â†’ general space expert system prompt.
    4. Always try Gemini first; fall back to deterministic only if AI fails.
    """

    sources = []
    context_parts = []
    has_system_data = bool(event_data or object_profile)

    if event_data:
        context_parts.append(build_event_context(event_data))
        sources.append({"kind": "conjunction_database_record"})
        # Include deterministic summary as additional grounding context
        context_parts.append(
            "DETERMINISTIC ANALYSIS:\n" + explain_event_deterministic(event_data)
        )

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

    # Choose the right system prompt based on whether we have live system data
    system_prompt = SYSTEM_PROMPT_GROUNDED if has_system_data else SYSTEM_PROMPT_GENERAL

    # Always attempt the LLM (Gemini) first for every question
    if ai_configured:
        llm_answer = _call_llm(question, context, system_prompt)

        if llm_answer:
            return CopilotResult(llm_answer, sources, "llm")

        # LLM call failed â€” log and fall through to deterministic
        print("[COPILOT] LLM call returned None, using deterministic fallback.")

    # ---- Deterministic fallback (no valid AI key or LLM call failed) ----
    if event_data and not kb_hits:
        answer = explain_event_deterministic(event_data)
    elif object_profile and not kb_hits:
        answer = explain_object_deterministic(object_profile)
    elif kb_hits:
        best = kb_hits[0]
        suffix = (
            "\n\n[Configure a valid Gemini API key for full conversational answers; "
            "this summary comes directly from the bundled reference docs.]"
            if not ai_configured else
            "\n\n[AI service temporarily unavailable â€” showing knowledge base excerpt.]"
        )
        answer = (
            f"From the scientific knowledge base ({best['title']}):\n\n"
            + best["excerpt"]
            + suffix
        )
    else:
        if not ai_configured:
            answer = (
                "No Gemini API key is configured. I can only answer from verified "
                "system data and the bundled knowledge base. Select an object or "
                "conjunction event in the dashboard, or ask about concepts like "
                "TLE, SGP4, TCA or miss distance.\n\n"
                "To enable full AI answers: add your GEMINI_API_KEY to backend/.env."
            )
        else:
            # AI configured but call failed
            answer = (
                "I encountered an issue connecting to the Gemini AI service. "
                "Please verify that GEMINI_API_KEY and AI_MODEL in backend/.env "
                "are correct (current model: " + (AI_MODEL or "not set") + ").\n\n"
                "Tip: Get a free Gemini API key at https://aistudio.google.com/apikey"
            )

    return CopilotResult(answer, sources, "deterministic")
