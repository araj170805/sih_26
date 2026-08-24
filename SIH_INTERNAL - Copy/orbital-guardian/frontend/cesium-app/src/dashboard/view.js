// =====================================================
// CESIUM VIEW LAYER
// Adapted from the original working main.js:
// TEME->fixed conversion, trajectories, TCA markers,
// pair isolation and camera control are preserved.
// =====================================================

import * as Cesium from "cesium";

export const viewer = new Cesium.Viewer("cesiumContainer", {
  animation: false,
  timeline: false,
  baseLayerPicker: true,
  geocoder: false,
  homeButton: false,
  sceneModePicker: false,
  navigationHelpButton: false,
});

viewer.scene.globe.enableLighting = true;

// Hide Cesium's own credits bar clutter; keep legal credit collapsed.
if (viewer.cesiumWidget?.creditContainer) {
  viewer.cesiumWidget.creditContainer.style.display = "none";
}

// -----------------------------------------------------
// STATE
// -----------------------------------------------------

export const trajectoryEntities = {}; // name -> {polyline, satellite}
let alertEntities = [];

export const RISK_COLORS = {
  CRITICAL: "#ff2d55",
  HIGH: "#ff8c1a",
  MEDIUM: "#ffd166",
  LOW: "#3ddc84",
};

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

// -----------------------------------------------------
// TEME -> EARTH-FIXED CONVERSION
// SGP4 outputs km in TEME; Cesium needs metres fixed.
// -----------------------------------------------------

function temeToFixed(positionKm, date) {
  const temePosition = new Cesium.Cartesian3(
    positionKm.x * 1000,
    positionKm.y * 1000,
    positionKm.z * 1000,
  );

  const matrix = Cesium.Transforms.computeTemeToPseudoFixedMatrix(
    date,
    new Cesium.Matrix3(),
  );

  return Cesium.Matrix3.multiplyByVector(
    matrix,
    temePosition,
    new Cesium.Cartesian3(),
  );
}

export function convertPoint(point) {
  return temeToFixed(point.position, Cesium.JulianDate.fromIso8601(point.time));
}

export function convertPositionObj(position, isoTime) {
  return temeToFixed(position, Cesium.JulianDate.fromIso8601(isoTime));
}

// -----------------------------------------------------
// TRAJECTORIES
// -----------------------------------------------------

export function clearAll() {
  viewer.entities.removeAll();

  for (const k of Object.keys(trajectoryEntities)) {
    delete trajectoryEntities[k];
  }

  alertEntities = [];
}

export function drawTrajectories(forecast) {
  forecast.objects.forEach((object, index) => {
    const color = SATELLITE_COLORS[index % SATELLITE_COLORS.length];

    const positions = object.points.map((p) => convertPoint(p));

    const polylineEntity = viewer.entities.add({
      name: `${object.name} - Trajectory`,
      polyline: {
        positions,
        width: 2.5,
        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower: 0.15,
          color,
        }),
      },
    });

    const sampledPosition = new Cesium.SampledPositionProperty();

    object.points.forEach((point) => {
      sampledPosition.addSample(
        Cesium.JulianDate.fromIso8601(point.time),
        convertPoint(point),
      );
    });

    const satelliteEntity = viewer.entities.add({
      name: object.name,
      position: sampledPosition,
      point: {
        pixelSize: 9,
        color,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 1,
      },
      label: {
        text: object.name,
        font: "12px 'Archivo', sans-serif",
        fillColor: color,
        showBackground: true,
        backgroundColor: Cesium.Color.BLACK.withAlpha(0.6),
        pixelOffset: new Cesium.Cartesian2(10, -10),
      },
      path: { show: false },
    });

    trajectoryEntities[object.name] = {
      polyline: polylineEntity,
      satellite: satelliteEntity,
    };
  });
}

export function drawConjunction(data) {
  const tcaIso = data.conjunction.tca;

  const positionA = convertPositionObj(data.position_a, tcaIso);
  const positionB = convertPositionObj(data.position_b, tcaIso);

  addTcaMarker(positionA, data.object_a.name);
  addTcaMarker(positionB, data.object_b.name);

  viewer.entities.add({
    name: "Minimum Separation",
    polyline: {
      positions: [positionA, positionB],
      width: 5,
      material: new Cesium.PolylineGlowMaterialProperty({
        glowPower: 0.4,
        color: Cesium.Color.RED,
      }),
    },
  });

  const midpoint = Cesium.Cartesian3.midpoint(
    positionA,
    positionB,
    new Cesium.Cartesian3(),
  );

  viewer.entities.add({
    name: "TCA",
    position: midpoint,
    point: {
      pixelSize: 9,
      color: Cesium.Color.ORANGE,
      outlineColor: Cesium.Color.WHITE,
      outlineWidth: 2,
    },
    label: {
      text: `TCA\n${data.conjunction.minimum_distance_km.toFixed(2)} km`,
      font: "13px 'JetBrains Mono', monospace",
      fillColor: Cesium.Color.ORANGE,
      showBackground: true,
      backgroundColor: Cesium.Color.BLACK.withAlpha(0.8),
      pixelOffset: new Cesium.Cartesian2(0, -22),
    },
  });

  return midpoint;
}

function addTcaMarker(position, label) {
  viewer.entities.add({
    name: `${label} @ TCA`,
    position,
    point: {
      pixelSize: 13,
      color: Cesium.Color.RED,
      outlineColor: Cesium.Color.WHITE,
      outlineWidth: 2,
    },
  });
}

// -----------------------------------------------------
// ALERT MARKERS
// -----------------------------------------------------

export function drawAlertMarkers(alerts) {
  clearAlertMarkers();

  for (const alert of alerts) {
    const positionA = convertPositionObj(alert.position_a, alert.tca);
    const positionB = convertPositionObj(alert.position_b, alert.tca);

    const midpoint = Cesium.Cartesian3.midpoint(
      positionA,
      positionB,
      new Cesium.Cartesian3(),
    );

    const cesiumColor = Cesium.Color.fromCssColorString(
      RISK_COLORS[alert.risk_level] || "#4da3ff",
    );

    alertEntities.push(
      viewer.entities.add({
        name: `${alert.object_a.name} Ã— ${alert.object_b.name}`,
        position: midpoint,
        point: {
          pixelSize: alert.risk_score >= 60 ? 12 : 8,
          color: cesiumColor,
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 1.5,
        },
      }),
    );
  }
}

export function clearAlertMarkers() {
  alertEntities.forEach((e) => viewer.entities.remove(e));
  alertEntities = [];
}

// -----------------------------------------------------
// VISIBILITY / CAMERA
// -----------------------------------------------------

export function isolatePair(nameA, nameB) {
  Object.keys(trajectoryEntities).forEach((name) => {
    const visible = name === nameA || name === nameB;
    trajectoryEntities[name].polyline.show = visible;
    trajectoryEntities[name].satellite.show = visible;
  });
}

export function showAllOrbits() {
  Object.values(trajectoryEntities).forEach((entry) => {
    entry.polyline.show = true;
    entry.satellite.show = true;
  });
}

export async function resetCamera() {
  showAllOrbits();
  await viewer.zoomTo(viewer.entities);
}

export function flyToPoint(cartesian, scale = 2.2) {
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.multiplyByScalar(
      cartesian,
      scale,
      new Cesium.Cartesian3(),
    ),
    duration: 1.6,
  });
}

export function flyToObject(name) {
  const entry = trajectoryEntities[name];

  if (!entry) return;

  const position = entry.satellite.position.getValue(viewer.clock.currentTime);

  if (position) flyToPoint(position, 1.6);
}
