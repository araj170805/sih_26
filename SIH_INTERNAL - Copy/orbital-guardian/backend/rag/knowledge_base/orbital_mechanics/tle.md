# Two-Line Element Sets (TLE)

A Two-Line Element set is a compact data format that encodes the orbital
elements of an Earth-orbiting object at a specific epoch.

## Format

Each record has three lines:
1. Object name
2. Line 1: epoch, first/second derivatives of mean motion, BSTAR drag term,
   element set number.
3. Line 2: inclination, right ascension of the ascending node, eccentricity,
   argument of perigee, mean anomaly, mean motion, revolution number.

## Epoch

Line 1 encodes the epoch — the moment in time when the elements were fitted
to observations. Accuracy degrades with element age because atmospheric drag
and perturbations continuously change the orbit.

## Limitations

- Mean elements, not osculating: they are fitted for use by SGP4.
- Typical accuracy for LEO is on the order of ~1 km at epoch and grows
  over time; TLEs are not precise enough for centimeter-level claims.
- The epoch should be as close as possible to the prediction window.
