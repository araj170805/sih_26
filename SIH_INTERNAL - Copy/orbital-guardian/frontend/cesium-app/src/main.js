import * as Cesium from "cesium";
import "./style.css";

// =====================================================
// CONFIG
// =====================================================

const API_URL = "http://127.0.0.1:8000";

// Quick-pick catalogue shown as preset buttons in the UI.
// Replaced by the LIVE catalog from GET /catalog once loaded;
// kept as offline fallback if the backend is unreachable.
const FALLBACK_SATELLITES = [
  { norad_id: 25544, name: "ISS (ZARYA)" },
  { norad_id: 28654, name: "NOAA 18" },
  { norad_id: 20580, name: "HST" },
  { norad_id: 48274, name: "CSS (TIANHE)" },
  { norad_id: 43058, name: "STARLINK-1130" },
];

let catalogObjects = FALLBACK_SATELLITES;

// Alerts from the last /screen run.
let currentAlerts = [];

// Trajectory entities indexed by object name,
// so a focused conjunction can isolate its pair.
let trajectoryEntities = {};

const HORIZON_PRESETS = [6, 12, 24, 48, 72];
const STEP_PRESETS = [1, 5, 10, 30];
const SPEED_PRESETS = [1, 2, 5, 10];

// Base simulation rate: 1x means 60 sim-seconds per real second.
const BASE_CLOCK_MULTIPLIER = 60;

// Mutable application state driven by the control panel.
const appState = {
  satellites: [25544, 28654],
  horizon_hours: 24,
  step_minutes: 1,
  playback_speed: 1,
};

// =====================================================
// CESIUM VIEWER
// =====================================================

const viewer = new Cesium.Viewer("cesiumContainer", {
  animation: true,
  timeline: true,
  baseLayerPicker: true,
  geocoder: false,
  homeButton: true,
  sceneModePicker: true,
  navigationHelpButton: false,
});

viewer.scene.globe.enableLighting = true;

// =====================================================
// UI CONTROLS
// =====================================================

function createControlPanel() {
  const panel = document.createElement("div");

  panel.id = "orbitalControlPanel";

  panel.innerHTML = `
        <div class="og-title">
            ORBITAL GUARDIAN
        </div>

        <div class="og-subtitle">
            CONJUNCTION ANALYSIS
        </div>

        <div class="og-divider"></div>

        <div class="og-section-title">FORECAST HORIZON</div>
        <div id="horizonButtons" class="og-button-row"></div>

        <div class="og-section-title">RESOLUTION</div>
        <div id="stepButtons" class="og-button-row"></div>

        <div class="og-divider"></div>

        <div class="og-section-title">SATELLITES</div>
        <div id="satelliteChips" class="og-chips"></div>

        <div class="og-add-row">
            <input
                id="noradInput"
                type="number"
                min="1"
                placeholder="NORAD ID"
            />
            <button id="addSatelliteBtn" title="Add satellite">+</button>
        </div>

        <div class="og-section-title">QUICK ADD</div>
        <div id="presetButtons" class="og-chips"></div>

        <div class="og-divider"></div>

        <button id="runAnalysisBtn">
            RUN ANALYSIS
        </button>

        <button id="screenButton">
            SCREEN CONJUNCTIONS
        </button>

        <button id="tcaButton">
            FLY TO TCA
        </button>

        <button id="homeButton">
            VIEW FULL ORBITS
        </button>

        <div class="og-divider"></div>

        <div class="og-section-title">RISK ALERTS</div>
        <div id="alertList" class="og-alerts">
            <div class="og-alert-empty">
                Select objects and run screening to
                detect upcoming conjunctions.
            </div>
        </div>

        <div class="og-divider"></div>

        <div class="og-section-title">PLAYBACK SPEED</div>
        <div id="speedButtons" class="og-button-row"></div>
        <button id="playPauseBtn">
            PAUSE
        </button>

        <div class="og-divider"></div>

        <div class="og-section">
            <span class="og-label">OBJECT A</span>
            <span id="objectAValue">---</span>
        </div>

        <div class="og-section">
            <span class="og-label">OBJECT B</span>
            <span id="objectBValue">---</span>
        </div>

        <div class="og-section">
            <span class="og-label">TCA</span>
            <span id="tcaValue">---</span>
        </div>

        <div class="og-section">
            <span class="og-label">MINIMUM SEPARATION</span>
            <span id="distanceValue">---</span>
        </div>

        <div class="og-section">
            <span class="og-label">RISK STATUS</span>
            <span id="riskValue">---</span>
        </div>

        <div id="loadingValue"></div>
    `;

  document.body.appendChild(panel);

  renderHorizonButtons();
  renderStepButtons();
  renderSatelliteChips();
  renderPresetButtons();
  renderSpeedButtons();

  // ---------------------------------------------
  // RUN ANALYSIS
  // ---------------------------------------------

  document
    .getElementById("runAnalysisBtn")
    .addEventListener("click", async () => {
      try {
        await loadVisualization();
      } catch (error) {
        console.error("Orbital Guardian visualization error:", error);

        const loading = document.getElementById("loadingValue");

        if (loading) {
          loading.textContent = "Load failed - see alert";
        }

        alert("Failed to load satellite visualization.\n\n" + error.message);
      }
    });

  // ---------------------------------------------
  // FLY TO TCA
  //
  // Zooms tightly onto the selected (or primary)
  // conjunction pair and isolates their orbits
  // so only the two involved objects are shown.
  // ---------------------------------------------

  document.getElementById("tcaButton").addEventListener("click", () => {
    if (window.selectedAlert) {
      focusAlert(window.selectedAlert);
      return;
    }

    if (!window.tcaPosition) {
      return;
    }

    if (window.primaryPair) {
      isolatePair(window.primaryPair[0], window.primaryPair[1]);
    }

    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.multiplyByScalar(
        window.tcaPosition,
        2.0,
        new Cesium.Cartesian3(),
      ),

      duration: 2,
    });
  });

  // ---------------------------------------------
  // VIEW FULL ORBITS
  // ---------------------------------------------

  document.getElementById("homeButton").addEventListener("click", async () => {
    showAllOrbits();

    await viewer.zoomTo(viewer.entities);
  });

  // ---------------------------------------------
  // SCREEN CONJUNCTIONS
  // ---------------------------------------------

  document
    .getElementById("screenButton")
    .addEventListener("click", async () => {
      await screenConjunctions();
    });

  // ---------------------------------------------
  // PLAY / PAUSE
  // ---------------------------------------------

  document.getElementById("playPauseBtn").addEventListener("click", () => {
    const button = document.getElementById("playPauseBtn");

    viewer.clock.shouldAnimate = !viewer.clock.shouldAnimate;

    button.textContent = viewer.clock.shouldAnimate ? "PAUSE" : "PLAY";
  });

  // ---------------------------------------------
  // ADD SATELLITE BY NORAD ID
  // ---------------------------------------------

  document.getElementById("addSatelliteBtn").addEventListener("click", () => {
    const input = document.getElementById("noradInput");

    const value = parseInt(input.value, 10);

    if (!value || value < 1) {
      return;
    }

    addSatellite(value);

    input.value = "";
  });

  document.getElementById("noradInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      document.getElementById("addSatelliteBtn").click();
    }
  });
}

// =====================================================
// CONFIG UI RENDERING
// =====================================================

function renderHorizonButtons() {
  const container = document.getElementById("horizonButtons");

  container.innerHTML = "";

  HORIZON_PRESETS.forEach((hours) => {
    const button = document.createElement("button");

    button.className = "og-toggle";
    button.textContent = `${hours}h`;

    if (appState.horizon_hours === hours) {
      button.classList.add("active");
    }

    button.addEventListener("click", () => {
      appState.horizon_hours = hours;

      container
        .querySelectorAll(".og-toggle")
        .forEach((el) => el.classList.remove("active"));

      button.classList.add("active");
    });

    container.appendChild(button);
  });
}

function renderStepButtons() {
  const container = document.getElementById("stepButtons");

  container.innerHTML = "";

  STEP_PRESETS.forEach((minutes) => {
    const button = document.createElement("button");

    button.className = "og-toggle";
    button.textContent = minutes < 60 ? `${minutes}m` : `${minutes / 60}h`;

    if (appState.step_minutes === minutes) {
      button.classList.add("active");
    }

    button.addEventListener("click", () => {
      appState.step_minutes = minutes;

      container
        .querySelectorAll(".og-toggle")
        .forEach((el) => el.classList.remove("active"));

      button.classList.add("active");
    });

    container.appendChild(button);
  });
}

function renderSpeedButtons() {
  const container = document.getElementById("speedButtons");

  container.innerHTML = "";

  SPEED_PRESETS.forEach((speed) => {
    const button = document.createElement("button");

    button.className = "og-toggle";
    button.textContent = `${speed}x`;

    if (appState.playback_speed === speed) {
      button.classList.add("active");
    }

    button.addEventListener("click", () => {
      setPlaybackSpeed(speed);

      container
        .querySelectorAll(".og-toggle")
        .forEach((el) => el.classList.remove("active"));

      button.classList.add("active");
    });

    container.appendChild(button);
  });
}

// Playback speed only changes visualization rate.
// It never changes the computed trajectory.

function setPlaybackSpeed(speed) {
  appState.playback_speed = speed;

  viewer.clock.multiplier = BASE_CLOCK_MULTIPLIER * speed;
}

function renderPresetButtons() {
  const container = document.getElementById("presetButtons");

  container.innerHTML = "";

  catalogObjects.forEach((satellite) => {
    const chip = document.createElement("button");

    const alreadySelected = appState.satellites.includes(satellite.norad_id);

    chip.className = alreadySelected ? "og-chip active" : "og-chip";

    chip.textContent = satellite.name;

    chip.addEventListener("click", () => {
      if (appState.satellites.includes(satellite.norad_id)) {
        removeSatellite(satellite.norad_id);
      } else {
        addSatellite(satellite.norad_id);
      }
    });

    container.appendChild(chip);
  });
}

function renderSatelliteChips() {
  const container = document.getElementById("satelliteChips");

  container.innerHTML = "";

  appState.satellites.forEach((noradId) => {
    const preset = catalogObjects.find((s) => s.norad_id === noradId);

    const label = preset ? preset.name : `NORAD ${noradId}`;

    const chip = document.createElement("div");

    chip.className = "og-chip selected";

    chip.innerHTML =
      `<span>${label}</span>` +
      `<button class="og-remove" title="Remove">x</button>`;

    chip
      .querySelector(".og-remove")
      .addEventListener("click", () => removeSatellite(noradId));

    container.appendChild(chip);
  });
}

function addSatellite(noradId) {
  if (appState.satellites.includes(noradId)) {
    return;
  }

  if (appState.satellites.length >= 8) {
    alert("Maximum 8 satellites per analysis.");
    return;
  }

  appState.satellites.push(noradId);

  renderSatelliteChips();
  renderPresetButtons();
}

function removeSatellite(noradId) {
  appState.satellites = appState.satellites.filter((id) => id !== noradId);

  renderSatelliteChips();
  renderPresetButtons();
}

// =====================================================
// LIVE CATALOG
// =====================================================

async function loadCatalog() {
  try {
    const response = await fetch(`${API_URL}/catalog?group=stations&limit=20`);

    if (!response.ok) {
      throw new Error(`Catalog API failed: ${response.status}`);
    }

    const data = await response.json();

    if (data.objects && data.objects.length > 0) {
      catalogObjects = data.objects;
      renderPresetButtons();
    }

    console.log(`Loaded ${data.count} live catalog objects`);
  } catch (error) {
    console.warn("Catalog unavailable, using fallback list:", error.message);
  }
}

// =====================================================
// CONJUNCTION SCREENING + RISK ALERTS
// =====================================================

const RISK_COLORS = {
  CRITICAL: "#ff2d2d",
  HIGH: "#ff8c1a",
  MEDIUM: "#ffd166",
  LOW: "#3ddc84",
};

async function screenConjunctions() {
  if (appState.satellites.length < 2) {
    alert("Select at least 2 objects to screen.");

    return;
  }

  const button = document.getElementById("screenButton");

  const loading = document.getElementById("loadingValue");

  button.disabled = true;

  loading.textContent = "Screening conjunctions...";

  try {
    const response = await fetch(`${API_URL}/screen`, {
      method: "POST",

      headers: {
        "Content-Type": "application/json",
      },

      body: JSON.stringify({
        objects: appState.satellites,
        horizon_hours: appState.horizon_hours,
        step_minutes: appState.step_minutes,
      }),
    });

    if (!response.ok) {
      const error = await response.json();

      throw new Error(error.detail || `Screening failed: ${response.status}`);
    }

    const data = await response.json();

    console.log("SCREENING RESULT:", data);

    currentAlerts = data.alerts;

    renderAlertList(data.screening);
    drawAlertMarkers();
  } catch (error) {
    alert(`Screening failed.\n\n${error.message}`);
  } finally {
    button.disabled = false;

    loading.textContent = "";
  }
}

function formatCountdown(hoursToTca) {
  if (hoursToTca < 0) {
    return "passed";
  }

  const hours = Math.floor(hoursToTca);

  const minutes = Math.round((hoursToTca - hours) * 60);

  return `+${hours}h ${minutes}m`;
}

function formatDistance(km) {
  if (km < 1) {
    return `${Math.round(km * 1000)} m`;
  }

  return `${km.toFixed(2)} km`;
}

function renderAlertList(screening) {
  const container = document.getElementById("alertList");

  container.innerHTML = "";

  if (currentAlerts.length === 0) {
    container.innerHTML =
      `<div class="og-alert-empty">` +
      `No flagged events within ` +
      `${screening.screen_threshold_km} km.` +
      `</div>`;

    return;
  }

  // ---------------------------------------------
  // SCREENING SUMMARY
  // ---------------------------------------------

  const summary = document.createElement("div");

  summary.className = "og-screening-summary";

  summary.textContent =
    `${screening.objects_screened} objects | ` +
    `${screening.pairs_screened} pairs | ` +
    `${currentAlerts.length} flagged`;

  container.appendChild(summary);

  // ---------------------------------------------
  // ALERT CARDS
  // ---------------------------------------------

  currentAlerts.forEach((alert, index) => {
    const color = RISK_COLORS[alert.risk_level];

    const card = document.createElement("div");

    card.className = "og-alert-card";

    card.style.borderLeftColor = color;

    card.innerHTML =
      `<div class="og-alert-header">` +
      `<span class="og-risk-badge" ` +
      `style="background:${color}">` +
      `${alert.risk_level}</span>` +
      `<span class="og-risk-score">` +
      `${alert.risk_score}/100</span>` +
      `</div>` +
      `<div class="og-alert-pair">${index + 1}. ` +
      `${alert.object_a.name} × ` +
      `${alert.object_b.name}</div>` +
      `<div class="og-alert-details">` +
      `<span>TCA ${formatCountdown(alert.hours_to_tca)}</span>` +
      `<span>${formatDistance(alert.minimum_distance_km)}</span> ` +
      `<span>${alert.relative_velocity_km_s.toFixed(1)} km/s</span>` +
      `</div>`;

    card.addEventListener("click", () => {
      focusAlert(alert);
    });

    container.appendChild(card);
  });
}

// =====================================================
// ALERT MARKERS ON THE GLOBE
// =====================================================

let alertEntities = [];

function clearAlertMarkers() {
  alertEntities.forEach((entity) => viewer.entities.remove(entity));

  alertEntities = [];
}

function drawAlertMarkers() {
  clearAlertMarkers();

  currentAlerts.forEach((alert) => {
    const positionA = convertConjunctionPosition(alert.position_a, alert.tca);

    const positionB = convertConjunctionPosition(alert.position_b, alert.tca);

    const midpoint = Cesium.Cartesian3.midpoint(
      positionA,
      positionB,
      new Cesium.Cartesian3(),
    );

    const color = RISK_COLORS[alert.risk_level];

    const cesiumColor = Cesium.Color.fromCssColorString(color);

    // Flagged TCA point
    alertEntities.push(
      viewer.entities.add({
        name: `${alert.object_a.name} x ` + `${alert.object_b.name}`,

        position: midpoint,

        point: {
          pixelSize: alert.risk_score >= 60 ? 14 : 9,

          color: cesiumColor,

          outlineColor: Cesium.Color.WHITE,

          outlineWidth: 2,
        },

        label: {
          text:
            `${alert.risk_level} ` +
            `${formatDistance(alert.minimum_distance_km)}`,

          font: "12px sans-serif",

          fillColor: cesiumColor,

          showBackground: true,

          backgroundColor: Cesium.Color.BLACK.withAlpha(0.8),

          pixelOffset: new Cesium.Cartesian2(0, -20),
        },
      }),
    );
  });
}

// =====================================================
// FOCUS AN ALERT — ISOLATE PAIR + ZOOM TO ITS TCA
// =====================================================

function updateReadouts(nameA, nameB, tca, distanceKm, risk) {
  document.getElementById("objectAValue").textContent = nameA;

  document.getElementById("objectBValue").textContent = nameB;

  document.getElementById("tcaValue").textContent = tca;

  document.getElementById("distanceValue").textContent =
    formatDistance(distanceKm);

  document.getElementById("riskValue").textContent = risk;
}

function focusAlert(alert) {
  // Remember the focused event so FLY TO TCA
  // re-uses it.
  window.selectedAlert = alert;

  // Show only the two involved objects.
  isolatePair(alert.object_a.name, alert.object_b.name);

  clearAlertMarkers();
  drawAlertMarkers();

  const positionA = convertConjunctionPosition(alert.position_a, alert.tca);

  const positionB = convertConjunctionPosition(alert.position_b, alert.tca);

  const midpoint = Cesium.Cartesian3.midpoint(
    positionA,
    positionB,
    new Cesium.Cartesian3(),
  );

  // Jump simulation time to the event and
  // zoom in close on the pair.
  viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(alert.tca);

  viewer.clock.shouldAnimate = false;

  document.getElementById("playPauseBtn").textContent = "PLAY";

  updateReadouts(
    alert.object_a.name,
    alert.object_b.name,
    new Date(alert.tca).toUTCString(),
    alert.minimum_distance_km,
    `${alert.risk_level} (${alert.risk_score}/100)`,
  );

  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.multiplyByScalar(
      midpoint,
      2.0,
      new Cesium.Cartesian3(),
    ),

    duration: 2,
  });
}

// =====================================================
// COLORS
// =====================================================

const SATELLITE_COLORS = [
  Cesium.Color.YELLOW,
  Cesium.Color.WHITE,
  Cesium.Color.CYAN,
  Cesium.Color.LIME,
  Cesium.Color.ORANGE,
  Cesium.Color.MAGENTA,
  Cesium.Color.CORNFLOWERBLUE,
  Cesium.Color.HOTPINK,
];

// =====================================================
// CONVERT SGP4 TEME -> CESIUM FIXED COORDINATES
// =====================================================
//
// SGP4 gives us position in TEME coordinates.
// Cesium uses Earth-fixed coordinates for visualization.
//
// Position from SGP4 is in kilometres.
// Cesium requires metres.
//
// =====================================================

function convertPosition(point) {
  const date = Cesium.JulianDate.fromIso8601(point.time);

  const temePosition = new Cesium.Cartesian3(
    point.position.x * 1000,
    point.position.y * 1000,
    point.position.z * 1000,
  );

  const temeToFixed = Cesium.Transforms.computeTemeToPseudoFixedMatrix(
    date,
    new Cesium.Matrix3(),
  );

  return Cesium.Matrix3.multiplyByVector(
    temeToFixed,
    temePosition,
    new Cesium.Cartesian3(),
  );
}

// =====================================================
// LOAD DATA FROM BACKEND
// =====================================================

async function loadVisualization() {
  console.log("Loading Orbital Guardian data...");

  if (appState.satellites.length < 2) {
    alert("Select at least 2 satellites for conjunction analysis.");
    return;
  }

  const loading = document.getElementById("loadingValue");

  loading.textContent = "Loading...";

  const requestBody = {
    objects: appState.satellites,
    horizon_hours: appState.horizon_hours,
    step_minutes: appState.step_minutes,
  };

  // =================================================
  // 1. GET FULL 24-HOUR TRAJECTORIES
  // =================================================

  console.log("Requesting /forecast...");

  const forecastResponse = await fetch(`${API_URL}/forecast`, {
    method: "POST",

    headers: {
      "Content-Type": "application/json",
    },

    body: JSON.stringify(requestBody),
  });

  if (!forecastResponse.ok) {
    throw new Error(`Forecast API failed: ${forecastResponse.status}`);
  }

  const forecast = await forecastResponse.json();

  console.log("FORECAST DATA:", forecast);

  // =================================================
  // 2. GET CONJUNCTION INFORMATION
  // =================================================

  console.log("Requesting /conjunction...");

  const conjunctionResponse = await fetch(`${API_URL}/conjunction`, {
    method: "POST",

    headers: {
      "Content-Type": "application/json",
    },

    body: JSON.stringify(requestBody),
  });

  if (!conjunctionResponse.ok) {
    throw new Error(`Conjunction API failed: ${conjunctionResponse.status}`);
  }

  const conjunction = await conjunctionResponse.json();

  console.log("CONJUNCTION DATA:", conjunction);

  // =================================================
  // 3. RESET PREVIOUS VISUALIZATION
  // =================================================

  viewer.entities.removeAll();

  trajectoryEntities = {};

  // =================================================
  // 4. DRAW TRAJECTORIES
  // =================================================

  drawTrajectories(forecast);

  // =================================================
  // 5. DRAW TCA + CLOSE APPROACH
  // =================================================

  drawConjunction(conjunction);

  // =================================================
  // 6. REDRAW ANY FLAGGED ALERT MARKERS
  // =================================================

  if (currentAlerts.length > 0) {
    drawAlertMarkers();
  }

  // =================================================
  // 7. SET CESIUM CLOCK
  // =================================================

  setupClock(forecast);

  // =================================================
  // 7. ZOOM TO EVERYTHING
  // =================================================

  await viewer.zoomTo(viewer.entities);

  loading.textContent = "";

  console.log("Visualization loaded successfully.");
}

// =====================================================
// DRAW FULL 24-HOUR TRAJECTORIES
// =====================================================

function drawTrajectories(forecast) {
  forecast.objects.forEach((object, index) => {
    const color = SATELLITE_COLORS[index % SATELLITE_COLORS.length];

    console.log(`Drawing ${object.name}: ${object.points.length} points`);

    // ---------------------------------------------
    // POLYLINE POSITIONS
    // ---------------------------------------------

    const positions = [];

    object.points.forEach((point) => {
      const position = convertPosition(point);

      positions.push(position);
    });

    // ---------------------------------------------
    // DRAW 24-HOUR ORBIT
    // ---------------------------------------------

    const polylineEntity = viewer.entities.add({
      name: `${object.name} - Trajectory`,

      polyline: {
        positions: positions,

        width: 3,

        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower: 0.15,

          color: color,
        }),
      },
    });

    // ---------------------------------------------
    // CREATE ANIMATED SATELLITE
    // ---------------------------------------------

    const sampledPosition = new Cesium.SampledPositionProperty();

    object.points.forEach((point) => {
      const time = Cesium.JulianDate.fromIso8601(point.time);

      const position = convertPosition(point);

      sampledPosition.addSample(time, position);
    });

    // ---------------------------------------------
    // SATELLITE ENTITY
    // ---------------------------------------------

    const satelliteEntity = viewer.entities.add({
      name: object.name,

      position: sampledPosition,

      point: {
        pixelSize: 10,

        color: color,

        outlineColor: Cesium.Color.BLACK,

        outlineWidth: 2,
      },

      label: {
        text: object.name,

        font: "14px sans-serif",

        fillColor: color,

        showBackground: true,

        backgroundColor: Cesium.Color.BLACK.withAlpha(0.65),

        pixelOffset: new Cesium.Cartesian2(10, -10),
      },

      path: {
        show: false,
      },
    });

    trajectoryEntities[object.name] = {
      polyline: polylineEntity,
      satellite: satelliteEntity,
    };

    console.log(`Added satellite entity: ${object.name}`);
  });
}

// =====================================================
// ORBIT ISOLATION — SHOW ONLY A FOCUSED PAIR
// =====================================================

function isolatePair(nameA, nameB) {
  Object.keys(trajectoryEntities).forEach((name) => {
    const visible = name === nameA || name === nameB;

    trajectoryEntities[name].polyline.show = visible;

    trajectoryEntities[name].satellite.show = visible;
  });
}

function showAllOrbits() {
  Object.values(trajectoryEntities).forEach((entry) => {
    entry.polyline.show = true;

    entry.satellite.show = true;
  });
}

// =====================================================
// DRAW CONJUNCTION / TCA
// =====================================================

function drawConjunction(data) {
  console.log("Drawing conjunction:", data);

  const positionA = convertConjunctionPosition(
    data.position_a,
    data.conjunction.tca,
  );

  const positionB = convertConjunctionPosition(
    data.position_b,
    data.conjunction.tca,
  );

  // =================================================
  // SATELLITE A @ TCA
  // =================================================

  viewer.entities.add({
    name: `${data.object_a.name} @ TCA`,

    position: positionA,

    point: {
      pixelSize: 16,

      color: Cesium.Color.RED,

      outlineColor: Cesium.Color.WHITE,

      outlineWidth: 3,
    },

    label: {
      text: `${data.object_a.name} @ TCA`,

      font: "15px sans-serif",

      fillColor: Cesium.Color.WHITE,

      showBackground: true,

      backgroundColor: Cesium.Color.RED.withAlpha(0.75),

      pixelOffset: new Cesium.Cartesian2(12, -12),
    },
  });

  // =================================================
  // SATELLITE B @ TCA
  // =================================================

  viewer.entities.add({
    name: `${data.object_b.name} @ TCA`,

    position: positionB,

    point: {
      pixelSize: 16,

      color: Cesium.Color.RED,

      outlineColor: Cesium.Color.WHITE,

      outlineWidth: 3,
    },

    label: {
      text: `${data.object_b.name} @ TCA`,

      font: "15px sans-serif",

      fillColor: Cesium.Color.WHITE,

      showBackground: true,

      backgroundColor: Cesium.Color.RED.withAlpha(0.75),

      pixelOffset: new Cesium.Cartesian2(12, -12),
    },
  });

  // =================================================
  // MINIMUM SEPARATION LINE
  // =================================================

  viewer.entities.add({
    name: "Minimum Separation",

    polyline: {
      positions: [positionA, positionB],

      width: 6,

      material: new Cesium.PolylineGlowMaterialProperty({
        glowPower: 0.4,

        color: Cesium.Color.RED,
      }),
    },
  });

  // =================================================
  // TCA MIDPOINT
  // =================================================

  const midpoint = Cesium.Cartesian3.midpoint(
    positionA,
    positionB,
    new Cesium.Cartesian3(),
  );

  window.tcaPosition = midpoint;

  window.primaryPair = [data.object_a.name, data.object_b.name];

  // =================================================
  // TCA LABEL
  // =================================================

  const distance = data.conjunction.minimum_distance_km;

  viewer.entities.add({
    name: "TCA",

    position: midpoint,

    point: {
      pixelSize: 10,

      color: Cesium.Color.ORANGE,

      outlineColor: Cesium.Color.WHITE,

      outlineWidth: 2,
    },

    label: {
      text: `TCA\n${distance.toFixed(2)} km`,

      font: "16px sans-serif",

      fillColor: Cesium.Color.ORANGE,

      showBackground: true,

      backgroundColor: Cesium.Color.BLACK.withAlpha(0.8),

      pixelOffset: new Cesium.Cartesian2(0, -25),
    },
  });

  console.log("Risk:", data.conjunction.status);

  window.selectedAlert = null;

  updateReadouts(
    data.object_a.name,
    data.object_b.name,
    new Date(data.conjunction.tca).toUTCString(),
    distance,
    data.conjunction.status,
  );
}

// =====================================================
// CONVERT CONJUNCTION POSITION
// =====================================================

function convertConjunctionPosition(position, timeString) {
  const date = Cesium.JulianDate.fromIso8601(timeString);

  const temePosition = new Cesium.Cartesian3(
    position.x * 1000,

    position.y * 1000,

    position.z * 1000,
  );

  const temeToFixed = Cesium.Transforms.computeTemeToPseudoFixedMatrix(
    date,

    new Cesium.Matrix3(),
  );

  return Cesium.Matrix3.multiplyByVector(
    temeToFixed,

    temePosition,

    new Cesium.Cartesian3(),
  );
}

// =====================================================
// CESIUM CLOCK
// =====================================================

function setupClock(forecast) {
  const start = Cesium.JulianDate.fromIso8601(forecast.forecast.start_time);

  const end = Cesium.JulianDate.addHours(
    start,

    forecast.forecast.horizon_hours,

    new Cesium.JulianDate(),
  );

  viewer.clock.startTime = start.clone();

  viewer.clock.stopTime = end.clone();

  viewer.clock.currentTime = start.clone();

  viewer.clock.clockRange = Cesium.ClockRange.LOOP_STOP;

  viewer.clock.multiplier = BASE_CLOCK_MULTIPLIER * appState.playback_speed;

  viewer.timeline.zoomTo(start, end);

  console.log("Clock configured:", start, end);
}

// =====================================================
// START APPLICATION
// =====================================================

createControlPanel();

loadCatalog();

loadVisualization()
  .catch((error) => {
    console.error("Orbital Guardian visualization error:", error);

    const loading = document.getElementById("loadingValue");

    if (loading) {
      loading.textContent = "Load failed - see alert";
    }

    alert("Failed to load satellite visualization.\n\n" + error.message);
  })
  .finally(() => {
    const loading = document.getElementById("loadingValue");

    // Only clear if it still shows the in-progress state.
    if (loading && loading.textContent === "Loading...") {
      loading.textContent = "";
    }
  });
