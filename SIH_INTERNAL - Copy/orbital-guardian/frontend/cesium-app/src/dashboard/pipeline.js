// =====================================================
// LIVE PIPELINE — renders the ACTUAL backend stages
// streamed over Server-Sent Events. No fake progress.
// =====================================================

import { getApiUrl } from "../api.js";

export const STAGES = [
  ["FETCHING_ORBITAL_DATA", "Data Fetching"],
  ["VALIDATING_DATA", "Data Validation"],
  ["PARSING_TLE", "TLE Parsing"],
  ["INITIALIZING_SGP4", "SGP4 Initialization"],
  ["PROPAGATING_ORBITS", "Orbit Propagation"],
  ["GENERATING_TRAJECTORIES", "Trajectory Generation"],
  ["BROAD_PHASE_SCREENING", "Pair Screening"],
  ["REFINING_CANDIDATES", "Candidate Refinement"],
  ["CALCULATING_TCA", "TCA Calculation"],
  ["CALCULATING_MINIMUM_SEPARATION", "Minimum Separation"],
  ["CALCULATING_RELATIVE_VELOCITY", "Relative Velocity"],
  ["CALCULATING_RISK", "Risk Assessment"],
  ["SAVING_RESULTS", "Saving Results"],
  ["COMPLETED", "Completed"],
];

const flow = document.getElementById("pipelineFlow");

let currentEventSource = null;

function reset() {
  flow.innerHTML = "";

  for (const [key, label] of STAGES) {
    const row = document.createElement("div");

    row.className = "pipe-stage";
    row.dataset.stage = key;

    row.innerHTML =
      `<span class="ps-icon">·</span>` +
      `<span>${label}</span>` +
      `<span class="ps-time"></span>`;

    flow.appendChild(row);
  }
}

function setStageState(stageKey, state, message, timing) {
  const rows = flow.querySelectorAll(".pipe-stage");

  for (const row of rows) {
    if (row.dataset.stage !== stageKey) continue;

    row.classList.remove("running", "done", "failed");

    if (state) row.classList.add(state);

    row.querySelector(".ps-icon").textContent =
      state === "done" ? "✓" : state === "running" ? "●" : state === "failed" ? "✕" : "·";

    row.querySelector(".ps-time").textContent = timing
      ? `${timing.toFixed(1)}s`
      : "";

    // Live counter message under the active stage.
    let msgRow = row.nextElementSibling;

    if (!msgRow || !msgRow.classList.contains("pipe-msg")) {
      msgRow = document.createElement("div");
      msgRow.className = "pipe-msg";
      row.after(msgRow);
    }

    msgRow.textContent = message || "";
  }
}

function markAllDoneUpTo(stageKey) {
  const order = STAGES.map(([k]) => k);
  const idx = order.indexOf(stageKey);

  for (let i = 0; i < idx; i++) {
    setStageState(order[i], "done");
  }
}

// -----------------------------------------------------
// SSE SUBSCRIPTION
// -----------------------------------------------------

export function subscribePipeline(jobRef, onCompleted, onFailed) {
  if (currentEventSource) {
    currentEventSource.close();
  }

  reset();

  const token = localStorage.getItem("og_access_token");

  const url =
    `${getApiUrl()}/analysis/${jobRef}/progress` +
    (token ? `?access_token=${encodeURIComponent(token)}` : "");

  const es = new EventSource(url);

  currentEventSource = es;

  es.onmessage = (event) => {
    let payload;

    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }

    handleEvent(payload, onCompleted, onFailed);

    if (payload.type === "completed" || payload.type === "failed") {
      es.close();
      currentEventSource = null;
    }
  };

  es.onerror = () => {
    es.close();
    currentEventSource = null;
  };
}

function handleEvent(payload, onCompleted, onFailed) {
  if (payload.type === "state") {
    // Replay snapshot from server — apply verbatim.
    return;
  }

  if (payload.type === "stage" || payload.type === "progress") {
    const timings = payload.timings || {};

    markAllDoneUpTo(payload.stage);

    for (const [key] of STAGES) {
      if (timings[key] != null) {
        setStageState(key, key === payload.stage ? "running" : "done",
          null, timings[key]);
      }
    }

    setStageState(payload.stage, "running", payload.message,
      timings[payload.stage]);
  }

  if (payload.type === "completed") {
    markAllDoneUpTo("COMPLETED");
    setStageState("COMPLETED", "done", null,
      (payload.counters || {}).duration_seconds);

    onCompleted?.(payload);
  }

  if (payload.type === "failed") {
    setStageState(payload.stage || "FETCHING_ORBITAL_DATA", "failed",
      `Error: ${payload.error}`);

    onFailed?.(payload);
  }
}
