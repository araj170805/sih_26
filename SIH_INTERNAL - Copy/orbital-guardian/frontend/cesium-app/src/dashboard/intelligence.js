// =====================================================
// RIGHT INTELLIGENCE PANEL
// Context-sensitive: analysis summary | object profile |
// conjunction intelligence. All data from real APIs.
// =====================================================

import { api, hasRole } from "../api.js";

const content = document.getElementById("intelligenceContent");

// Shared copilot context, updated by renderers.
export const copilotContext = {
  noradId: null,
  conjunctionId: null,
  profile: null,
  eventRisk: null,
};

// -----------------------------------------------------
// HELPERS
// -----------------------------------------------------

function esc(value) {
  return String(value ?? "â€”").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function fmtKm(km) {
  if (km == null) return "â€”";
  if (km < 1) return `${Math.round(km * 1000)} m`;
  return `${Number(km).toFixed(2)} km`;
}

function fmtCountdown(hours) {
  if (hours == null) return "â€”";
  if (hours < 0) return "passed";
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  return `T+${h}h ${m}m`;
}

export { esc, fmtKm, fmtCountdown };

function section(title, inner) {
  return `<div class="ii-section"><h5>${esc(title)}</h5>${inner}</div>`;
}

function kvList(pairs) {
  return (
    `<dl class="kv">` +
    pairs
      .map(
        ([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`,
      )
      .join("") +
    `</dl>`
  );
}

// -----------------------------------------------------
// ANALYSIS SUMMARY MODE
// -----------------------------------------------------

export function showSummary(summary = null) {
  copilotContext.noradId = null;
  copilotContext.conjunctionId = null;
  copilotContext.profile = null;
  copilotContext.eventRisk = null;

  const body = summary
    ? kvList([
        ["Objects screened", esc(summary.objects_screened)],
        ["Pairs screened", esc(summary.pairs_screened)],
        ["Flagged events", esc(summary.pairs_flagged)],
        ["Screen radius", esc(`${summary.screen_threshold_km} km`)],
        ["Horizon", esc(`${summary.horizon_hours} h @ ${summary.step_minutes} min`)],
      ]) +
      `<p class="explain-text" style="margin-top:.7rem">Click an alert or any object on the globe for full intelligence.</p>`
    : `<p>Select objects and run an analysis, or click any object to open its intelligence profile.</p>`;

  content.innerHTML = `
    <div class="ii-header">
      <div class="ii-kicker">ANALYSIS SUMMARY</div>
      <div class="ii-title">MISSION OVERVIEW</div>
    </div>
    ${section("CURRENT RUN", body)}
    <div class="ii-section">
      <h5>SOURCE TRANSPARENCY</h5>
      <div class="source-line">Orbital data: CelesTrak (primary) via cache chain</div>
      <div class="source-line">Propagation: SGP4 reference implementation</div>
      <div class="source-line">Risk model: Operational Risk Priority v1 (heuristic)</div>
    </div>`;
}

// -----------------------------------------------------
// OBJECT INTELLIGENCE MODE
// -----------------------------------------------------

export async function showObjectProfile(noradId) {
  content.innerHTML = `<div class="ii-empty"><p>Loading object intelligenceâ€¦</p></div>`;

  let profile;

  try {
    profile = await api(`/objects/${noradId}/profile`);
  } catch (error) {
    content.innerHTML = `
      <div class="ii-header"><div class="ii-kicker">OBJECT INTELLIGENCE</div>
      <div class="ii-title">NORAD ${esc(noradId)}</div></div>
      <div class="ii-section"><p class="explain-text">${esc(error.message)}</p></div>`;
    return;
  }

  copilotContext.noradId = noradId;
  copilotContext.conjunctionId = null;
  copilotContext.profile = profile;
  copilotContext.eventRisk = null;

  const identity = profile.identity;
  const mission = profile.mission || {};
  const status = profile.status || {};
  const orbit = profile.live_orbit || {};
  const quality = profile.data_quality || {};
  const ctx = profile.conjunction_context;

  const typeBadge = `<span class="badge ${identity.object_type === "DEBRIS" ? "MEDIUM" : identity.object_type === "ROCKET BODY" ? "HIGH" : "LOW"}">${esc(identity.object_type)}</span>`;
  const statusBadge = `<span class="badge ${status.status === "OPERATIONAL" ? "LOW" : status.status === "UNKNOWN" ? "MONITOR" : "MEDIUM"}">${esc(status.status)}</span>`;
  const freshBadge = `<span class="fresh-${esc(quality.freshness)}" style="font-size:.66rem;font-weight:700;letter-spacing:.14em">${esc(quality.freshness)}</span>`;

  // Mission block â€” honest about missing metadata.
  let missionHtml;

  if (mission._debris_context) {
    missionHtml = `<p class="explain-text">${esc(mission._debris_context)}</p>`;
  } else if (mission._rocket_body_context) {
    missionHtml = `<p class="explain-text">${esc(mission._rocket_body_context)}</p>`;
  } else if (mission.mission_name || mission.operator) {
    missionHtml = kvList([
      ["Mission", esc(mission.mission_name)],
      ["Category", esc(mission.mission_category)],
      ["Operator", esc(mission.operator)],
      ["Country", esc(mission.country)],
      ["Launch vehicle", esc(mission.launch_vehicle)],
      ["Launch date", esc(mission.launch_date)],
      ["Launch site", esc(mission.launch_site)],
    ]) +
      (mission.mission_purpose
        ? `<p class="explain-text" style="margin-top:.6rem"><b style="color:var(--accent)">WHY IT WAS SENT TO SPACE:</b> ${esc(mission.mission_purpose)}</p>`
        : "") +
      (mission.mission_description
        ? `<p class="explain-text">${esc(mission.mission_description)}</p>`
        : "");
  } else {
    missionHtml = `<p class="explain-text">${esc(
      mission._unavailable_reason ||
        "No verified mission metadata available.",
    )}</p>`;
  }

  // End-of-life block — verified facts or labeled heuristic.
  const eol = profile.end_of_life || {};

  let eolHtml = kvList([
    ["Expected reentry", esc(eol.expected_reentry || "Not documented")],
  ]);

  if (eol.estimated_orbital_lifetime) {
    eolHtml += `<div style="height:.5rem"></div>` + kvList([
      ["Est. orbital lifetime", esc(eol.estimated_orbital_lifetime)],
    ]);
  }

  if (eol.basis) {
    eolHtml += `<p class="explain-text" style="font-size:.66rem;margin-top:.5rem;color:var(--text-muted)">${esc(eol.basis)}</p>`;
  }

  // Conjunction context.
  let conjHtml = `<p class="explain-text">No conjunction events recorded for this object in the local database.</p>`;

  if (ctx?.upcoming_events?.length) {
    conjHtml = ctx.upcoming_events
      .map(
        (e) => `
      <div class="event-row" data-event-id="${e.conjunction_id}">
        <span>NORAD ${esc(e.other_norad_id)}</span>
        <span class="mono">${new Date(e.tca).toUTCString().slice(5, 22)}</span>
        <span class="mono">${fmtKm(e.minimum_distance_km)}</span>
        <span class="badge ${esc(e.risk_status)}">${esc(e.risk_status)}</span>
      </div>`,
      )
      .join("");
  }

  content.innerHTML = `
    <div class="ii-header">
      <div class="ii-kicker">OBJECT INTELLIGENCE</div>
      <div class="ii-title">${esc(identity.object_name)}</div>
      <div class="ii-sub">NORAD ${esc(identity.norad_id)} · INTL DESIG ${esc(identity.international_designator)}</div>
      <div class="ii-badges">${typeBadge} ${statusBadge} ${freshBadge}</div>
    </div>

    ${section("LIVE ORBIT",
      kvList([
        ["Latitude", esc(orbit.latitude_deg) + "°"],
        ["Longitude", esc(orbit.longitude_deg) + "°"],
        ["Altitude", esc(orbit.altitude_km) + " km"],
        ["Velocity", esc(orbit.velocity_km_s) + " km/s"],
        ["Inclination", esc(orbit.inclination_deg) + "°"],
        ["Apogee", esc(orbit.apogee_altitude_km) + " km"],
        ["Perigee", esc(orbit.perigee_altitude_km) + " km"],
        ["Period", esc(orbit.orbital_period_min) + " min"],
        ["Epoch", esc((orbit.tle_epoch || "").slice(0, 16)) + "Z"],
      ]))}

    ${section("DATA QUALITY",
      kvList([
        ["TLE age", esc(quality.tle_age_hours) + " h"],
        ["Freshness", freshBadge],
        ["Confidence", esc(quality.confidence_score) + "%"],
        ["Source", esc(quality.orbital_data_source)],
      ]))}

    ${section("MISSION INTELLIGENCE", missionHtml)}

    ${section("END OF LIFE", eolHtml)}

    ${section("CONJUNCTION CONTEXT", conjHtml)}

    ${section("SOURCES",
      (profile.sources || [])
        .map((s) => `<div class="source-line">${esc(s.kind)}: ${esc(s.source)}</div>`)
        .join("") +
      `<div class="source-line">Profile generated: ${esc((profile.profile_generated_at || "").slice(0, 19))}Z</div>`)}`;

  content.querySelectorAll("[data-event-id]").forEach((row) => {
    row.addEventListener("click", () =>
      showEventIntelligence(parseInt(row.dataset.eventId, 10)),
    );
  });
}

// -----------------------------------------------------
// CONJUNCTION INTELLIGENCE MODE
// -----------------------------------------------------

export async function showEventIntelligence(conjunctionId) {
  content.innerHTML = `<div class="ii-empty"><p>Loading event intelligenceâ€¦</p></div>`;

  let risk;

  try {
    risk = await api(`/conjunctions/${conjunctionId}/risk`);
  } catch (error) {
    content.innerHTML = `
      <div class="ii-header"><div class="ii-kicker">CONJUNCTION INTELLIGENCE</div></div>
      <div class="ii-section"><p class="explain-text">${esc(error.message)}</p></div>`;
    return;
  }

  copilotContext.noradId = null;
  copilotContext.conjunctionId = conjunctionId;
  copilotContext.profile = null;
  copilotContext.eventRisk = risk;

  const bars = risk.contributions
    .map(
      (c) => `
    <div class="riskbar-block">
      <div class="riskbar-label">
        <span>${esc(c.factor)}</span>
        <span>${c.earned} / ${c.max}</span>
      </div>
      <div class="riskbar"><i style="width:${
        c.max ? Math.round((c.earned / c.max) * 100) : 0
      }%"></i></div>
    </div>`,
    )
    .join("");

  content.innerHTML = `
    <div class="ii-header">
      <div class="ii-kicker">OPERATIONAL RISK PRIORITY</div>
      <div class="big-score">
        <b>${esc(risk.risk_score ?? "â€”")}<span style="font-size:.9rem;color:var(--text-muted)">/100</span></b>
        <span class="badge ${esc(risk.risk_level)}">${esc(risk.risk_level)}</span>
      </div>
    </div>

    ${section("RISK DRIVERS", bars)}

    ${section("DATA CONFIDENCE", kvList([
      ["Confidence", esc(risk.confidence != null ? risk.confidence + "%" : "â€”")],
    ]))}

    ${section("WHY THIS RANKING", `<p class="explain-text">${esc(risk.deterministic_explanation)}</p>`)}

    <div class="ii-section">
      <button class="og-btn small primary" id="explainEventBtn">✦ EXPLAIN THIS EVENT</button>
      <button class="og-btn small" id="genReportBtn" style="margin-left:.4rem">GENERATE REPORT</button>
      <button class="og-btn small" id="replayFromPanel" style="margin-left:.4rem">REPLAY ENCOUNTER</button>
    </div>

    ${section("METHODOLOGY & DISCLAIMER", `<p class="explain-text">${esc(risk.disclaimer)} Deterministic two-phase SGP4 screening; values inherit TLE uncertainty that grows after epoch.</p>`)}`;

  document.getElementById("explainEventBtn")?.addEventListener("click", () => {
    window.__copilotExplainEvent?.();
  });

  document.getElementById("genReportBtn")?.addEventListener("click", generateReport);

  document.getElementById("replayFromPanel")?.addEventListener("click", () => {
    window.__startReplay?.(conjunctionId);
  });
}

async function generateReport() {
  try {
    const result = await api(
      `/reports/conjunction/${copilotContext.conjunctionId}`,
      { method: "POST" },
    );

    window.open(`/reports/${result.report_id}/html`, "_blank");
  } catch (error) {
    alert(`Report generation failed: ${error.message}`);
  }
}
