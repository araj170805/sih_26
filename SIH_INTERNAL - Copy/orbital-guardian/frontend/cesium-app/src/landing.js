// =====================================================
// LANDING PAGE — live capabilities + animated orbits
// =====================================================

import { api } from "./api.js";

// -----------------------------------------------------
// ANIMATED ORBITAL RINGS (canvas)
// -----------------------------------------------------

const canvas = document.getElementById("orbitCanvas");
const ctx = canvas.getContext("2d");

let width = 0;
let height = 0;
let stars = [];

function resize() {
  const dpr = window.devicePixelRatio || 1;

  width = canvas.clientWidth * dpr;
  height = canvas.clientHeight * dpr;

  canvas.width = width;
  canvas.height = height;

  stars = Array.from({ length: 180 }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    r: Math.random() * 1.4 + 0.3,
    tw: Math.random() * Math.PI * 2,
    speed: 0.5 + Math.random() * 1.2,
  }));
}

window.addEventListener("resize", resize);
resize();

function drawOrbit(cx, cy, rx, ry, angle, color, lineWidth) {
  ctx.save();
  ctx.translate(width / 2, height / 2);

  // Tilt the orbital plane for depth
  ctx.transform(1, 0.28, 0, 1, 0, 0);

  ctx.beginPath();
  ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.stroke();

  // Object on the orbit
  const px = Math.cos(angle) * rx;
  const py = Math.sin(angle) * ry;

  ctx.beginPath();
  ctx.arc(px, py, 4.5, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.shadowColor = color;
  ctx.shadowBlur = 10;
  ctx.fill();

  ctx.restore();
}

function frame(time) {
  ctx.clearRect(0, 0, width, height);

  // Starfield with subtle twinkle
  for (const star of stars) {
    const alpha = 0.3 + 0.4 * Math.sin(star.tw + time * 0.001 * star.speed);

    ctx.globalAlpha = alpha;
    ctx.fillStyle = "#f5d0ba";
    ctx.beginPath();
    ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.globalAlpha = 1;

  const cx = width / 2;
  const cy = height / 2;
  const base = Math.min(width, height);

  // Orbital Guardian signature colors: Orange / Amber / Copper
  drawOrbit(cx, cy, base * 0.42, base * 0.42, time * 0.00022,
    "rgba(255, 107, 53, 0.35)", 1.2);
  drawOrbit(cx, cy, base * 0.30, base * 0.30, -time * 0.00034,
    "rgba(255, 179, 71, 0.45)", 1.4);
  drawOrbit(cx, cy, base * 0.18, base * 0.18, time * 0.00055,
    "rgba(255, 140, 90, 0.65)", 1.8);

  // Central body (Earth representation)
  const gradient = ctx.createRadialGradient(cx, cy, 4, cx, cy, base * 0.08);
  gradient.addColorStop(0, "#ff6b35");
  gradient.addColorStop(0.5, "#802b0c");
  gradient.addColorStop(1, "#0f0805");

  ctx.beginPath();
  ctx.arc(cx, cy, base * 0.065, 0, Math.PI * 2);
  ctx.fillStyle = gradient;
  ctx.shadowColor = "rgba(255, 107, 53, 0.5)";
  ctx.shadowBlur = 20;
  ctx.fill();
  ctx.shadowBlur = 0;

  requestAnimationFrame(frame);
}

requestAnimationFrame(frame);

// -----------------------------------------------------
// LIVE STATS — real backend data
// -----------------------------------------------------

async function loadLiveStats() {
  const objectsEl = document.getElementById("statObjects");
  const systemEl = document.getElementById("statSystem");

  try {
    const health = await api("/health");

    systemEl.textContent =
      health.status === "healthy" ? "OPERATIONAL" : "DEGRADED";

    systemEl.style.color =
      health.status === "healthy" ? "var(--success)" : "var(--warning)";
  } catch {
    systemEl.textContent = "API OFFLINE";
    systemEl.style.color = "var(--danger)";
  }

  try {
    const catalog = await api("/catalog?group=visual&limit=200");

    objectsEl.textContent = `${catalog.count}+`;
  } catch {
    objectsEl.textContent = "—";
  }
}

loadLiveStats();

// -----------------------------------------------------
// CAPABILITY GRID — reflects actual backend state
// -----------------------------------------------------

const CAPABILITIES = [
  { key: null, title: "SGP4 Trajectory Propagation",
    desc: "Deterministic orbit prediction up to 72 hours using the reference SGP4 model and live CelesTrak TLEs.", online: true },
  { key: null, title: "Conjunction Screening & TCA Refinement",
    desc: "Broad-phase all-pairs screening with 1-second-resolution closest-approach refinement and relative velocity at TCA.", online: true },
  { key: null, title: "Explainable Risk Prioritization",
    desc: "Transparent Operational Risk Priority scoring with per-factor breakdown — never a black box.", online: true },
  { key: null, title: "3D Encounter Replay",
    desc: "Cesium globe replay of close approaches with synchronized timeline, follow-cams and separation readout.", online: true },
  { key: null, title: "Object Intelligence Profiles",
    desc: "Identity, mission context, live orbital state, data freshness and conjunction history per NORAD ID.", online: true },
  { key: null, title: "AI Space Intelligence Copilot",
    desc: "Context-aware explanations grounded in real event data and a scientific knowledge base.",
    flagKey: "ai_copilot" },
];

function renderCapabilities(flags = {}) {
  const grid = document.getElementById("capGrid");
  if (!grid) return;

  grid.innerHTML = "";

  for (const cap of CAPABILITIES) {
    const optionalOff =
      cap.flagKey && flags[cap.flagKey] === false && Object.keys(flags).length > 0;

    const card = document.createElement("div");

    card.className = "cap-card" + (optionalOff ? " offline" : "");

    card.innerHTML = `
      <b><span class="cap-dot" style="background:${
        optionalOff ? "var(--text-muted)" : "var(--success)"
      }"></span>${cap.title}</b>
      <small>${cap.desc}${
        optionalOff
          ? ' <em style="color:var(--warning)">[Configuration Required]</em>'
          : ""
      }</small>
    `;

    grid.appendChild(card);
  }
}

api("/health")
  .then((h) => h.integrations || {})
  .then(renderCapabilities)
  .catch(() => renderCapabilities());
