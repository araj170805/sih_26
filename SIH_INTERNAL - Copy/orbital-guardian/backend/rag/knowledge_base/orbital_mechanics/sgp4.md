# SGP4 Propagation Model

SGP4 (Simplified General Perturbations 4) is the standard analytic orbit
propagation model used with TLE data.

## What it does

Given a TLE's mean elements, SGP4 predicts position and velocity at any time
near the epoch by modeling:
- Secular drift from Earth oblateness (J2) and atmospheric drag
- Long-period and short-period periodic perturbations

## Deterministic nature

SGP4 is a closed-form analytical model: identical inputs always produce
identical outputs. It involves no randomness or machine learning. Orbital
Guardian uses it exclusively for all position/velocity calculations.

## Coordinate frame

SGP4 output is expressed in the TEME (True Equator, Mean Equinox) frame.
Visualization systems convert TEME to Earth-fixed coordinates using sidereal
time rotation.

## Error growth

Prediction error grows with distance from the TLE epoch, dominated by
unmodeled drag variations. A 24-hour forecast typically carries uncertainty
of order kilometers; this is why conjunction screening uses thresholds much
larger than object sizes.
