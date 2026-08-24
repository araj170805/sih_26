// =====================================================
// ORBITAL GUARDIAN — MISSION CONTROL DASHBOARD
// =====================================================

import * as Cesium from "cesium";
import { onAuthStateChanged, signOut } from "firebase/auth";
import {
  api,
  clearSession,
  getUser,
  hasRole,
  isLoggedIn,
  saveSession,
  setFirebaseAuth,
} from "../api.js";
import { getApiUrl } from "../api.js";
import firebaseAuth, { firebaseReady } from "../firebase.js";

// Route every API call through the Firebase ID token.
setFirebaseAuth(firebaseAuth);
import {
  RISK_COLORS,
  clearAll,
  drawAlertMarkers,
  drawConjunction,
  drawTrajectories,
  flyToPoint,
  isolatePair,
  resetCamera,
  showAllOrbits,
  trajectoryEntities,
  viewer,
} from "./view.js";
import { subscribePipeline } from "./pipeline.js";
import {
  copilotContext,
  fmtKm,
  showEventIntelligence,
  showObjectProfile,
  showSummary,
} from "./intelligence.js";

// -----------------------------------------------------
// APP STATE
// -----------------------------------------------------

const HORIZON_PRESETS = [6, 12, 24, 48, 72];
const STEP_PRESETS = [1, 5, 10, 30];
const SPEED_PRESETS = [1, 2, 5, 10];
const BASE_CLOCK_MULTIPLIER = 60;

let catalogObjects = [];
let currentAlerts = [];
let activeJobRef = null;
let tcaInfo = null; // {iso, position} for JUMP TO TCA
let replayData = null;
let followName = null;

const appState = {
  satellites: [25544, 28654],
  horizon_hours: 24,
  step_minutes: 1,
  playback_speed: 1,
};

// =====================================================
// TOP BAR
// =====================================================

setInterval(() => {
  const el = document.getElementById("utcClock");
  if (el) el.textContent = `${new Date().toISOString().slice(11, 19)} UTC`;
}, 1000);

async function refreshSystemStatus() {
  const pill = document.getElementById("systemStatus");

  try {
    const health = await api("/health");

    pill.className = `status-pill ${
      health.status === "healthy" ? "online" : "degraded"
    }`;

    pill.innerHTML = `<i></i>${health.status.toUpperCase()}`;
  } catch {
    pill.className = "status-pill offline";
    pill.innerHTML = "<i></i>API OFFLINE";
  }
}

refreshSystemStatus();
setInterval(refreshSystemStatus, 60000);

// ---------------- NOTIFICATIONS ----------------

document.getElementById("notifBtn")?.addEventListener("click", async () => {
  const panel = document.getElementById("notifPanel");

  if (!panel.hidden) {
    panel.hidden = true;
    return;
  }

  panel.hidden = false;

  try {
    const data = await api("/notifications?limit=20");

    document.getElementById("notifCount").hidden = !data.unread_count;

    if (data.unread_count) {
      document.getElementById("notifCount").textContent = data.unread_count;
    }

    panel.innerHTML = data.notifications.length
      ? data.notifications
          .map(
            (n) => `
        <div class="notif-item ${n.read ? "" : "unread"}" data-id="${n.id}">
          <div class="n-title">${n.title}</div>
          ${n.body ? `<div class="n-body">${n.body}</div>` : ""}
          <div class="n-time">${new Date(n.created_at).toUTCString().slice(5, 22)} UTC</div>
        </div>`,
          )
          .join("")
      : `<div class="pm-item">No notifications.</div>`;

    panel.querySelectorAll(".notif-item").forEach((item) => {
      item.addEventListener("click", async () => {
        await api(`/notifications/${item.dataset.id}/read`, { method: "POST" });
        item.classList.remove("unread");
        refreshNotificationCount();
      });
    });
  } catch {
    panel.innerHTML = `<div class="pm-item">Sign in to see notifications.</div>`;
  }
});

async function refreshNotificationCount() {
  if (!isLoggedIn()) return;

  try {
    const data = await api("/notifications?limit=1");
    const el = document.getElementById("notifCount");
    el.hidden = !data.unread_count;
    if (data.unread_count) el.textContent = data.unread_count;
  } catch {
    /* ignore */
  }
}

// ---------------- PROFILE MENU ----------------

async function refreshBackendProfile() {
  // Exchange the current Firebase token for our role mapping.
  if (!firebaseReady || !firebaseAuth?.currentUser) return;

  try {
    const idToken = await firebaseAuth.currentUser.getIdToken();

    const profile = await api("/auth/firebase-session", {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    });

    saveSession({ user: profile });

    initProfile();
    loadWatchlists();
  } catch {
    /* backend offline — keep cached profile */
  }
}

function initProfile() {
  const fbUser = firebaseAuth?.currentUser;
  const user = getUser();
  const nameEl = document.getElementById("profileName");
  const avatarEl = document.getElementById("userAvatar");
  const details = document.getElementById("pmUserDetails");

  const displayName =
    (user && user.username) ||
    (fbUser && (fbUser.displayName || fbUser.email));

  if (displayName) {
    nameEl.textContent = String(displayName).toUpperCase().slice(0, 18);
    avatarEl.textContent = String(displayName).slice(0, 2).toUpperCase();

    details.hidden = false;
    details.innerHTML = `<b>${(fbUser && fbUser.email) || (user && user.email) || ""}</b>` +
      `<span>ROLE: ${(user && user.role) || "VIEWER"}</span>`;

    document.getElementById("pmLogin").style.display = "none";
    document.getElementById("pmRegister").style.display = "none";
    document.getElementById("pmLogout").hidden = false;
    document.getElementById("pmSystem").classList.remove("hidden-admin");

    // Single-role platform: signed-in operators unlock everything.
    document.getElementById("watchlistSection").hidden = false;

    document.getElementById("authHint").hidden = true;
  } else {
    nameEl.textContent = "GUEST";
    avatarEl.textContent = "?";

    details.hidden = true;
    document.getElementById("pmLogout").hidden = true;
    document.getElementById("pmSystem").classList.add("hidden-admin");
    document.getElementById("watchlistSection").hidden = true;
    document.getElementById("authHint").hidden = false;
  }
}

// React to Firebase sign-in/out events.
if (firebaseAuth) {
  onAuthStateChanged(firebaseAuth, () => {
    initProfile();
    refreshBackendProfile();
    refreshNotificationCount();
  });
}

document.getElementById("profileBtn").addEventListener("click", () => {
  document.getElementById("profileMenu").hidden =
    !document.getElementById("profileMenu").hidden;
});

document.addEventListener("click", (event) => {
  const menu = document.getElementById("profileMenu");

  if (!menu.hidden && !event.target.closest(".profile-wrap")) menu.hidden = true;

  const notif = document.getElementById("notifPanel");

  if (!notif.hidden && !event.target.closest(".notif-wrap")) notif.hidden = true;
});

document.getElementById("pmLogout")?.addEventListener("click", async () => {
  try {
    if (firebaseReady && firebaseAuth?.currentUser) {
      await signOut(firebaseAuth);
    }
  } catch {
    /* ignore */
  }

  clearSession();
  location.href = "/login.html";
});

// ---------------- SIDEBAR TOGGLE ----------------

document.getElementById("sidebarToggle").addEventListener("click", () => {
  document.getElementById("leftPanel").classList.toggle("collapsed");
});

// collapsible sections
document.querySelectorAll(".collapse-toggle").forEach((toggle) => {
  toggle.addEventListener("click", () =>
    toggle.closest(".collapsible").classList.toggle("open"),
  );
});

// =====================================================
// LEFT PANEL — CONFIG CONTROLS
// =====================================================

function renderToggles(containerId, values, key, format) {
  const container = document.getElementById(containerId);

  container.innerHTML = "";

  values.forEach((value) => {
    const button = document.createElement("button");

    button.className =
      "og-toggle" + (appState[key] === value ? " active" : "");

    button.textContent = format(value);

    button.addEventListener("click", () => {
      appState[key] = value;
      renderToggles(containerId, values, key, format);
    });

    container.appendChild(button);
  });
}

function renderChips() {
  const selectedBox = document.getElementById("satelliteChips");

  selectedBox.innerHTML = "";

  appState.satellites.forEach((noradId) => {
    const preset = catalogObjects.find((s) => s.norad_id === noradId);

    const label = preset ? preset.name : `NORAD ${noradId}`;

    const chip = document.createElement("div");

    chip.className = "og-chip selected";

    chip.innerHTML = `<span>${label}</span><button class="og-remove">×</button>`;

    chip.querySelector(".og-remove").addEventListener("click", () => {
      appState.satellites = appState.satellites.filter((id) => id !== noradId);
      renderChips();
    });

    chip.querySelector("span").addEventListener("click", () => {
      flyToObjectByName(label);
      showObjectProfile(noradId);
    });

    selectedBox.appendChild(chip);
  });

  // Quick-add presets from live catalog.
  const presetBox = document.getElementById("presetChips");

  presetBox.innerHTML = "";

  catalogObjects.slice(0, 12).forEach((satellite) => {
    const selected = appState.satellites.includes(satellite.norad_id);

    const chip = document.createElement("button");

    chip.className = "og-chip" + (selected ? " selected" : "");
    chip.textContent = satellite.name;

    chip.addEventListener("click", () => toggleSatellite(satellite));

    presetBox.appendChild(chip);
  });
}

function toggleSatellite(satellite) {
  if (appState.satellites.includes(satellite.norad_id)) {
    appState.satellites = appState.satellites.filter(
      (id) => id !== satellite.norad_id,
    );
  } else {
    if (appState.satellites.length >= 8) {
      alert("Maximum 8 objects per analysis.");
      return;
    }

    appState.satellites.push(satellite.norad_id);
  }

  renderChips();
}

function addByNorad(value) {
  const noradId = parseInt(value, 10);

  if (!noradId || noradId < 1) return;

  if (appState.satellites.includes(noradId)) return;

  if (appState.satellites.length >= 8) {
    alert("Maximum 8 objects per analysis.");
    return;
  }

  appState.satellites.push(noradId);

  renderChips();
}

document.getElementById("addSatelliteBtn").addEventListener("click", () => {
  addByNorad(document.getElementById("noradInput").value);

  document.getElementById("noradInput").value = "";
});

document.getElementById("noradInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("addSatelliteBtn").click();
});

// ---------------- OBJECT SEARCH ----------------

const searchBox = document.getElementById("objectSearch");
const searchResults = document.getElementById("searchResults");

let searchTimer = null;

searchBox.addEventListener("input", () => {
  clearTimeout(searchTimer);

  const query = searchBox.value.trim();

  if (query.length < 2) {
    searchResults.hidden = true;
    return;
  }

  searchTimer = setTimeout(async () => {
    try {
      const groups = ["stations", "visual"];
      let matches = [];

      for (const group of groups) {
        const data = await api(`/objects?group=${group}&limit=200`);
        matches = matches.concat(data.objects);
      }

      matches = Object.values(
        Object.fromEntries(matches.map((o) => [o.norad_id, o])),
      ).filter((o) => o.name.toLowerCase().includes(query.toLowerCase()));

      searchResults.innerHTML = matches.length
        ? matches.slice(0, 8).map((o) => `
            <div class="search-result" data-norad="${o.norad_id}">
              <span>${o.name}</span>
              <small>${o.norad_id}</small>
            </div>`)
          .join("")
        : `<div class="search-result"><span>No matches</span></div>`;

      searchResults.hidden = false;

      searchResults.querySelectorAll("[data-norad]").forEach((row) => {
        row.addEventListener("click", () => {
          const noradId = parseInt(row.dataset.norad, 10);

          if (!appState.satellites.includes(noradId)) addByNorad(noradId);

          searchResults.hidden = true;
          searchBox.value = "";
        });
      });
    } catch {
      searchResults.hidden = true;
    }
  }, 300);
});

// ---------------- WATCHLISTS ----------------

async function loadWatchlists() {
  if (!hasRole("ANALYST")) return;

  const box = document.getElementById("watchlistList");

  try {
    const data = await api("/watchlists");

    box.innerHTML = data.watchlists.length
      ? ""
      : `<div class="empty-hint">No watchlists yet.</div>`;

    for (const wl of data.watchlists) {
      const row = document.createElement("div");

      row.className = "wl-item";

      row.innerHTML = `
        <span class="wl-name">${wl.name}</span>
        <span class="wl-count">${wl.objects.length} obj</span>
        <button class="wl-del" title="Delete">×</button>`;

      row.querySelector(".wl-name").addEventListener("click", async () => {
        // Load watchlist objects into the selection.
        appState.satellites = wl.objects.map((o) => o.norad_id);

        renderChips();

        try {
          const events = await api(`/watchlists/${wl.id}/conjunctions`);

          if (events.events.length) {
            currentAlerts = events.events.map((e) => ({
              conjunction_id: e.id,
              object_a: { norad_id: e.object_a_norad_id, name: `NORAD ${e.object_a_norad_id}` },
              object_b: { norad_id: e.object_b_norad_id, name: `NORAD ${e.object_b_norad_id}` },
              tca: e.tca,
              hours_to_tca:
                (new Date(e.tca) - Date.now()) / 3600000,
              minimum_distance_km: e.minimum_distance_km,
              relative_velocity_km_s: e.relative_velocity_km_s,
              risk_score: e.risk_score ?? 0,
              risk_level: e.risk_status,
            }));

            renderAlertList({
              screen_threshold_km: null,
              pairs_screened: "watchlist history",
            });

            drawAlertMarkers(currentAlerts);
          }
        } catch {
          /* ignore */
        }
      });

      row.querySelector(".wl-del").addEventListener("click", async () => {
        if (!confirm(`Delete watchlist "${wl.name}"?`)) return;

        await api(`/watchlists/${wl.id}`, { method: "DELETE" });
        loadWatchlists();
      });

      box.appendChild(row);
    }
  } catch {
    box.innerHTML = `<div class="empty-hint">Watchlists unavailable.</div>`;
  }
}

document.getElementById("createWatchlistBtn").addEventListener("click", async () => {
  const input = document.getElementById("watchlistName");

  if (!input.value.trim()) return;

  try {
    await api("/watchlists", {
      method: "POST",
      body: JSON.stringify({ name: input.value.trim() }),
    });

    input.value = "";
    loadWatchlists();
  } catch (error) {
    alert(error.message);
  }
});

// =====================================================
// ANALYSIS JOBS (real backend pipeline + SSE)
// =====================================================

function requireLogin() {
  if (isLoggedIn()) return true;

  alert(
    "Sign in to run analysis jobs — every registered operator has full access.\n\nUse the profile menu (top right) to sign in.",
  );

  return false;
}

async function startJob(kind) {
  if (appState.satellites.length < 2) {
    alert(kind === "screen"
      ? "Select at least 2 objects to screen."
      : "Select at least 2 satellites for conjunction analysis.");
    return;
  }

  if (!requireLogin()) return;

  const button = kind === "screen"
    ? document.getElementById("screenButton")
    : document.getElementById("runAnalysisBtn");

  button.disabled = true;

  const originalText = button.textContent;

  button.textContent = "STARTING JOB...";

  try {
    const job = await api("/analysis/start", {
      method: "POST",
      body: JSON.stringify({
        objects: appState.satellites,
        horizon_hours: appState.horizon_hours,
        step_minutes: appState.step_minutes,
      }),
    });

    activeJobRef = job.job_ref;

    subscribePipeline(
      job.job_ref,

      // onCompleted -> fetch full results via /analysis/{ref}
      async (payload) => {
        button.disabled = false;
        button.textContent = originalText;

        try {
          const state = await api(`/analysis/${job.job_ref}`);

          if (state.status === "COMPLETED") {
            const summary = state.result || {};

            // Fetch ranked alerts by re-running a lightweight
            // sync screen is wasteful — instead use persisted
            // conjunctions endpoint filtered client-side.
            const conj = await api(`/conjunctions?limit=50`);

            currentAlerts = mapPersistedToAlerts(conj.conjunctions);

            renderAlertList(summary);
            drawAlertMarkers(currentAlerts);

            refreshNotificationCount();

            if (!currentAlerts.length && summary.objects_screened) {
              await loadVisualization(false);
            }
          }
        } catch (error) {
          console.error(error);
        }
      },

      (payload) => {
        button.disabled = false;
        button.textContent = originalText;

        alert(`Analysis failed:\n\n${payload.error}`);
      },
    );

    button.textContent = "RUNNING...";
  } catch (error) {
    button.disabled = false;
    button.textContent = originalText;
    alert(`Could not start job:\n\n${error.message}`);
  }
}

function mapPersistedToAlerts(records) {
  // Persisted records are newest-first; keep upcoming ones only.
  const now = Date.now();
  const selectedNames = new Map(
    catalogObjects.map((o) => [o.norad_id, o.name]),
  );

  return records
    .filter((r) => new Date(r.tca).getTime() >= now - 3600_000)
    .slice(0, 20)
    .map((r) => ({
      conjunction_id: r.id,
      object_a: {
        norad_id: r.satellite_a_norad_id,
        name: selectedNames.get(r.satellite_a_norad_id) ||
          `NORAD ${r.satellite_a_norad_id}`,
      },
      object_b: {
        norad_id: r.satellite_b_norad_id,
        name: selectedNames.get(r.satellite_b_norad_id) ||
          `NORAD ${r.satellite_b_norad_id}`,
      },
      tca: r.tca,
      hours_to_tca: (new Date(r.tca) - now) / 3600000,
      minimum_distance_km: r.minimum_distance_km,
      relative_velocity_km_s: r.relative_velocity_km_s,
      risk_score: r.risk_score ?? 0,
      risk_level: r.risk_status,
    }))
    .sort((a, b) => b.risk_score - a.risk_score);
}

document.getElementById("runAnalysisBtn")
  .addEventListener("click", () => startJob("forecast"));

document.getElementById("screenButton")
  .addEventListener("click", () => startJob("screen"));

// =====================================================
// ALERT LIST
// =====================================================

function formatCountdown(hours) {
  if (hours == null) return "";
  if (hours < 0) return "passed";
  return `+${Math.floor(hours)}h ${Math.round((hours % 1) * 60)}m`;
}

function renderAlertList(screening) {
  const container = document.getElementById("alertList");

  container.innerHTML = "";

  if (!currentAlerts.length) {
    container.innerHTML = `<div class="empty-hint">No flagged events within the screening window.</div>`;
    return;
  }

  if (screening?.objects_screened != null) {
    const summary = document.createElement("div");

    summary.className = "screening-summary";

    summary.textContent =
      `${screening.objects_screened} OBJECTS · ` +
      `${screening.pairs_screened} PAIRS · ` +
      `${currentAlerts.length} FLAGGED`;

    container.appendChild(summary);
  }

  currentAlerts.forEach((alert, index) => {
    const color = RISK_COLORS[alert.risk_level] || "#4da3ff";

    const card = document.createElement("div");

    card.className = "alert-card";

    card.style.borderLeftColor = color;

    card.innerHTML = `
      <div class="alert-head">
        <span class="badge ${alert.risk_level}">${alert.risk_level}</span>
        <span class="alert-score" style="color:${color}">${
          alert.risk_score ?? "—"
        }/100</span>
      </div>
      <div class="alert-pair">${index + 1}. ${alert.object_a.name} × ${alert.object_b.name}</div>
      <div class="alert-details">
        <span>TCA ${formatCountdown(alert.hours_to_tca)}</span>
        <span>${fmtKm(alert.minimum_distance_km)}</span>
        ${
          alert.relative_velocity_km_s != null
            ? `<span>${Number(alert.relative_velocity_km_s).toFixed(1)} km/s</span>`
            : ""
        }
      </div>`;

    card.addEventListener("click", () => focusAlert(alert));

    container.appendChild(card);
  });
}

async function focusAlert(alert) {
  if (alert.conjunction_id) {
    await showEventIntelligence(alert.conjunction_id);

    // Try real replay data.
    startReplay(alert.conjunction_id).catch(() => {
      focusWithForecastData(alert);
    });

    return;
  }

  focusWithForecastData(alert);
}

function focusWithForecastData(alert) {
  isolatePair(alert.object_a.name, alert.object_b.name);

  viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(alert.tca);

  viewer.clock.shouldAnimate = false;

  updatePlayPauseButton();

  // Fly to midpoint of the pair's current positions.
  const entryA = trajectoryEntities[alert.object_a.name];
  const entryB = trajectoryEntities[alert.object_b.name];

  if (entryA && entryB) {
    const posA = entryA.satellite.position.getValue(viewer.clock.currentTime);
    const posB = entryB.satellite.position.getValue(viewer.clock.currentTime);

    if (posA && posB) {
      flyToPoint(
        Cesium.Cartesian3.midpoint(posA, posB, new Cesium.Cartesian3()),
        2.4,
      );
    }
  }

  setTcaMarker(alert.tca);
}

// =====================================================
// VIEW MODES
// =====================================================

document.querySelectorAll("#viewModes button").forEach((button) => {
  button.addEventListener("click", async () => {
    document
      .querySelectorAll("#viewModes button")
      .forEach((b) => b.classList.remove("active"));

    button.classList.add("active");

    const mode = button.dataset.mode;

    if (mode === "global") {
      await resetCamera();
    } else if (mode === "focus") {
      const first = appState.satellites[0];

      if (first != null) {
        const entry = Object.entries(trajectoryEntities).find(
          ([name]) => name.includes(String(first)),
        );

        if (entry) flyToPoint(
          entry[1].satellite.position.getValue(viewer.clock.currentTime),
          1.8,
        );
      }
    } else if (mode === "conjunction" && currentAlerts.length) {
      focusAlert(currentAlerts[0]);
    }
  });
});

document.getElementById("resetCamBtn").addEventListener("click", resetCamera);

function flyToObjectByName(name) {
  const entry = trajectoryEntities[name];

  if (!entry) return;

  const position = entry.satellite.position.getValue(viewer.clock.currentTime);

  if (position) flyToPoint(position, 1.7);
}

// =====================================================
// TIMELINE (synced with Cesium clock)
// =====================================================

const tlTrack = document.getElementById("tlTrack");
const tlHandle = document.getElementById("tlHandle");
const tlProgress = document.getElementById("tlProgress");
const tlCurrent = document.getElementById("tlCurrent");
const tlStart = document.getElementById("tlStart");
const tlEnd = document.getElementById("tlEnd");
const tlTcaMarker = document.getElementById("tlTcaMarker");

viewer.clock.onTick.addEventListener(() => {
  const start = viewer.clock.startTime;
  const end = viewer.clock.stopTime;
  const now = viewer.clock.currentTime;

  if (!start || !end) return;

  const total = Cesium.JulianDate.secondsDifference(end, start);

  const elapsed = Cesium.JulianDate.secondsDifference(now, start);

  const fraction = Math.min(Math.max(elapsed / total, 0), 1);

  tlHandle.style.left = `${fraction * 100}%`;
  tlProgress.style.width = `${fraction * 100}%`;

  tlCurrent.textContent = `${Cesium.JulianDate.toDate(now)
    .toISOString()
    .slice(11, 19)}Z`;
});

function setupClock(startIso, horizonHours) {
  const start = Cesium.JulianDate.fromIso8601(startIso);
  const end = Cesium.JulianDate.addHours(
    start,
    horizonHours,
    new Cesium.JulianDate(),
  );

  viewer.clock.startTime = start.clone();
  viewer.clock.stopTime = end.clone();
  viewer.clock.currentTime = start.clone();
  viewer.clock.clockRange = Cesium.ClockRange.LOOP_STOP;
  viewer.clock.multiplier = BASE_CLOCK_MULTIPLIER * appState.playback_speed;
  viewer.clock.shouldAnimate = true;

  tlStart.textContent = `${Cesium.JulianDate.toDate(start)
    .toISOString()
    .slice(11, 19)}Z`;
  tlEnd.textContent = `${Cesium.JulianDate.toDate(end)
    .toISOString()
    .slice(11, 19)}Z`;

  updatePlayPauseButton();
}

// Scrubbing.
let scrubbing = false;

function seekFromEvent(event) {
  const rect = tlTrack.getBoundingClientRect();

  const fraction = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);

  const total = Cesium.JulianDate.secondsDifference(
    viewer.clock.stopTime,
    viewer.clock.startTime,
  );

  viewer.clock.currentTime = Cesium.JulianDate.addSeconds(
    viewer.clock.startTime,
    fraction * total,
    new Cesium.JulianDate(),
  );
}

tlTrack.addEventListener("pointerdown", (e) => {
  scrubbing = true;
  seekFromEvent(e);
});

window.addEventListener("pointermove", (e) => {
  if (scrubbing) seekFromEvent(e);
});

window.addEventListener("pointerup", () => {
  scrubbing = false;
});

// Play / pause.
const playPauseBtn = document.getElementById("tlPlayPause");

playPauseBtn.addEventListener("click", () => {
  viewer.clock.shouldAnimate = !viewer.clock.shouldAnimate;
  updatePlayPauseButton();
});

function updatePlayPauseButton() {
  playPauseBtn.textContent = viewer.clock.shouldAnimate ? "⏸" : "▶";
}

function renderSpeedButtons() {
  const container = document.getElementById("speedButtons");

  container.innerHTML = "";

  SPEED_PRESETS.forEach((speed) => {
    const button = document.createElement("button");

    button.className =
      "og-toggle" + (appState.playback_speed === speed ? " active" : "");

    button.textContent = `${speed}×`;

    button.addEventListener("click", () => {
      appState.playback_speed = speed;

      viewer.clock.multiplier = BASE_CLOCK_MULTIPLIER * speed;

      renderSpeedButtons();
    });

    container.appendChild(button);
  });
}

// TCA jump.
function setTcaMarker(iso) {
  tcaInfo = { iso };

  tlTcaMarker.hidden = false;

  const start = viewer.clock.startTime;
  const end = viewer.clock.stopTime;

  if (!start || !end) return;

  const tcaJulian = Cesium.JulianDate.fromIso8601(iso);

  const total = Cesium.JulianDate.secondsDifference(end, start);

  const offset = Cesium.JulianDate.secondsDifference(tcaJulian, start);

  tlTcaMarker.style.left = `${Math.min(Math.max((offset / total) * 100, 0), 100)}%`;

  document.getElementById("tlJumpTca").disabled = false;
  document.getElementById("replayEventBtn").disabled = false;
}

document.getElementById("tlJumpTca").addEventListener("click", () => {
  if (!tcaInfo) return;

  viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(tcaInfo.iso);

  viewer.clock.shouldAnimate = false;

  updatePlayPauseButton();
});

// =====================================================
// FORECAST VISUALIZATION
// =====================================================

async function loadVisualization(resetView = true) {
  if (appState.satellites.length < 2) {
    alert("Select at least 2 satellites for conjunction analysis.");
    return;
  }

  const body = JSON.stringify({
    objects: appState.satellites,
    horizon_hours: appState.horizon_hours,
    step_minutes: appState.step_minutes,
  });

  const headers = { "Content-Type": "application/json" };

  const forecastResponse = await fetch(`${getApiUrl()}/forecast`, {
    method: "POST",
    headers,
    body,
  });

  if (!forecastResponse.ok) {
    throw new Error(`Forecast API failed: ${forecastResponse.status}`);
  }

  const forecast = await forecastResponse.json();

  const conjunctionResponse = await fetch(`${getApiUrl()}/conjunction`, {
    method: "POST",
    headers,
    body,
  });

  if (!conjunctionResponse.ok) {
    throw new Error(`Conjunction API failed: ${conjunctionResponse.status}`);
  }

  const conjunction = await conjunctionResponse.json();

  clearAll();

  drawTrajectories(forecast);

  const midpoint = drawConjunction(conjunction);

  setTcaMarker(conjunction.conjunction.tca);

  setupClock(forecast.forecast.start_time, forecast.forecast.horizon_hours);

  if (currentAlerts.length) drawAlertMarkers(currentAlerts);

  if (resetView) await viewer.zoomTo(viewer.entities);

  showSummary({
    objects_screened: forecast.objects.length,
    pairs_screened:
      forecast.objects.length * (forecast.objects.length - 1) / 2,
    pairs_flagged: conjunction.events?.length ?? 1,
    screen_threshold_km: "—",
    horizon_hours: forecast.forecast.horizon_hours,
    step_minutes: forecast.forecast.step_minutes,
  });
}

// =====================================================
// ENCOUNTER REPLAY (real /timeline data)
// =====================================================

async function startReplay(conjunctionId) {
  const data = await api(`/conjunctions/${conjunctionId}/timeline`);

  replayData = data;

  isolatePair(data.object_a_name, data.object_b_name);

  // Build sampled positions from REAL timeline steps.
  clearReplayEntities();

  const times = data.steps.map((s) => Cesium.JulianDate.fromIso8601(s.time));

  const positionsA = data.steps.map((s) =>
    new Cesium.Cartesian3(
      s.position_a.x * 1000, s.position_a.y * 1000, s.position_a.z * 1000,
    ),
  );

  const positionsB = data.steps.map((s) =>
    new Cesium.Cartesian3(
      s.position_b.x * 1000, s.position_b.y * 1000, s.position_b.z * 1000,
    ),
  );

  // NOTE: SGP4 positions are TEME; for the short replay window we
  // rotate each sample individually below instead of bulk-assigning.
  const propertyA = new Cesium.SampledPositionProperty();
  const propertyB = new Cesium.SampledPositionProperty();

  data.steps.forEach((step) => {
    const julian = Cesium.JulianDate.fromIso8601(step.time);

    const fixedA = temeToFixedForReplay(step.position_a, julian);
    const fixedB = temeToFixedForReplay(step.position_b, julian);

    propertyA.addSample(julian, fixedA);
    propertyB.addSample(julian, fixedB);
  });

  void times; void positionsA; void positionsB;

  const colorA = Cesium.Color.CYAN;
  const colorB = Cesium.Color.ORANGE;

  replayEntityA = viewer.entities.add({
    name: data.object_a_name,
    position: propertyA,
    point: { pixelSize: 11, color: colorA, outlineWidth: 1,
             outlineColor: Cesium.Color.BLACK },
    label: {
      text: data.object_a_name,
      font: "12px 'Archivo'",
      fillColor: colorA,
      showBackground: true,
      backgroundColor: Cesium.Color.BLACK.withAlpha(0.6),
      pixelOffset: new Cesium.Cartesian2(10, -10),
    },
  });

  replayEntityB = viewer.entities.add({
    name: data.object_b_name,
    position: propertyB,
    point: { pixelSize: 11, color: colorB, outlineWidth: 1,
             outlineColor: Cesium.Color.BLACK },
    label: {
      text: data.object_b_name,
      font: "12px 'Archivo'",
      fillColor: colorB,
      showBackground: true,
      backgroundColor: Cesium.Color.BLACK.withAlpha(0.6),
      pixelOffset: new Cesium.Cartesian2(10, -10),
    },
  });

  // Hide non-replay trajectories for focus mode.
  Object.keys(trajectoryEntities).forEach((name) => {
    const visible =
      name === data.object_a_name || name === data.object_b_name;

    trajectoryEntities[name].polyline.show = visible;
    trajectoryEntities[name].satellite.show = visible;
  });

  // Clock over the replay window at a usable rate.
  const startJ = Cesium.JulianDate.fromIso8601(data.steps[0].time);
  const endJ = Cesium.JulianDate.fromIso8601(
    data.steps[data.steps.length - 1].time,
  );

  viewer.clock.startTime = startJ.clone();
  viewer.clock.stopTime = endJ.clone();
  viewer.clock.currentTime = startJ.clone();
  viewer.clock.multiplier = 30;
  viewer.clock.shouldAnimate = true;

  setTcaMarker(data.tca);

  // Camera to the TCA region.
  const tcaStep = data.steps[Math.floor(data.steps.length / 2)];

  flyToPoint(
    temeToFixedForReplay(tcaStep.position_a, startJ),
    1.35,
  );

  updatePlayPauseButton();
}

let replayEntityA = null;
let replayEntityB = null;

function clearReplayEntities() {
  if (replayEntityA) viewer.entities.remove(replayEntityA);
  if (replayEntityB) viewer.entities.remove(replayEntityB);

  replayEntityA = null;
  replayEntityB = null;
}

function temeToFixedForReplay(positionKm, julian) {
  const temePosition = new Cesium.Cartesian3(
    positionKm.x * 1000,
    positionKm.y * 1000,
    positionKm.z * 1000,
  );

  const matrix = Cesium.Transforms.computeTemeToPseudoFixedMatrix(
    julian,
    new Cesium.Matrix3(),
  );

  return Cesium.Matrix3.multiplyByVector(
    matrix,
    temePosition,
    new Cesium.Cartesian3(),
  );
}

document.getElementById("replayEventBtn").addEventListener("click", () => {
  const id = copilotContext.conjunctionId ??
    currentAlerts.find((a) => a.conjunction_id)?.conjunction_id;

  if (id == null) {
    alert("No conjunction event selected.");
    return;
  }

  startReplay(id).catch((error) =>
    alert(`Replay unavailable: ${error.message}`),
  );
});

// Follow-object controls during replay.
document.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() === "f" && replayEntityA) {
    const position = replayEntityA.position.getValue(
      viewer.clock.currentTime,
    );

    if (position) flyToPoint(position, 1.15);
  }

  if (event.key.toLowerCase() === "g" && replayEntityB) {
    const position = replayEntityB.position.getValue(
      viewer.clock.currentTime,
    );

    if (position) flyToPoint(position, 1.15);
  }
});

// =====================================================
// COPILOT DOCK
// =====================================================

const copilotDock = document.getElementById("copilotDock");
const copilotMessages = document.getElementById("copilotMessages");

document.getElementById("copilotFab").addEventListener("click", () => {
  copilotDock.hidden = !copilotDock.hidden;
});

document.getElementById("copilotClose").addEventListener("click", () => {
  copilotDock.hidden = true;
});

function addCopilotMessage(text, who) {
  const div = document.createElement("div");

  div.className = `cd-msg ${who}`;

  div.textContent = text;

  copilotMessages.appendChild(div);

  copilotMessages.scrollTop = copilotMessages.scrollHeight;

  return div;
}

async function askCopilot(question) {
  addCopilotMessage(question, "user");

  const thinking = addCopilotMessage("Analyzing verified system data...", "bot");

  try {
    const response = await api("/ai/chat", {
      method: "POST",
      body: JSON.stringify({
        question,
        norad_id: copilotContext.noradId,
        conjunction_id: copilotContext.conjunctionId,
      }),
    });

    thinking.textContent = response.answer;

    document.getElementById("copilotMode").textContent =
      response.provider_configured && response.mode === "llm"
        ? "GEMINI LIVE"
        : "deterministic mode";
  } catch (error) {
    thinking.textContent = `Copilot error: ${error.message}`;
  }
}

document.getElementById("copilotForm").addEventListener("submit", (event) => {
  event.preventDefault();

  const input = document.getElementById("copilotInput");

  if (!input.value.trim()) return;

  askCopilot(input.value.trim());

  input.value = "";
});

// Exposed hook used by intelligence panel's EXPLAIN THIS EVENT.
window.__copilotExplainEvent = async () => {
  if (copilotContext.conjunctionId == null) return;

  copilotDock.hidden = false;

  const thinking = addCopilotMessage(
    "Generating grounded explanation...",
    "bot",
  );

  try {
    const result = await api("/ai/explain-event", {
      method: "POST",
      body: JSON.stringify({
        conjunction_id: copilotContext.conjunctionId,
      }),
    });

    thinking.textContent = result.answer;
  } catch (error) {
    thinking.textContent = `Copilot error: ${error.message}`;
  }
};

// =====================================================
// BOOTSTRAP
// =====================================================

renderToggles("horizonButtons", HORIZON_PRESETS, "horizon_hours", (h) => `${h}h`);
renderToggles("stepButtons", STEP_PRESETS, "step_minutes", (m) =>
  m < 60 ? `${m}m` : `${m / 60}h`);
renderSpeedButtons();
renderChips();
initProfile();
loadWatchlists();
refreshNotificationCount();
showSummary();

// Load live catalog (fallback list if unreachable).
const FALLBACK_SATELLITES = [
  { norad_id: 25544, name: "ISS (ZARYA)" },
  { norad_id: 28654, name: "NOAA 18" },
  { norad_id: 20580, name: "HST" },
  { norad_id: 48274, name: "CSS (TIANHE)" },
  { norad_id: 43058, name: "STARLINK-1130" },
];

catalogObjects = FALLBACK_SATELLITES;

api("/catalog?group=stations&limit=20")
  .then((data) => {
    if (data.objects?.length) {
      catalogObjects = catalogObjects.concat(
        data.objects.filter(
          (o) => !FALLBACK_SATELLITES.some((f) => f.norad_id === o.norad_id),
        ),
      );
    }

    renderChips();
  })
  .catch(() => renderChips());

// Initial visualization with defaults (guest-friendly v1 endpoints).
loadVisualization(true).catch((error) => {
  console.warn("Initial visualization failed:", error.message);
});
