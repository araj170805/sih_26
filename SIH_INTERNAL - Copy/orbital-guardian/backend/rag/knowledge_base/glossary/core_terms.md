# Glossary

- **NORAD ID**: Unique catalog number assigned to each tracked space object.
- **TLE**: Two-Line Element set; snapshot of orbital elements at an epoch.
- **Epoch**: The reference time of an element set.
- **SGP4**: Standard analytical propagation model used with TLEs.
- **TEME**: True Equator Mean Equinox coordinate frame of SGP4 output.
- **TCA**: Time of Closest Approach between two objects.
- **Miss Distance**: Separation distance at TCA.
- **Conjunction**: A predicted close approach between two objects.
- **Broad phase**: Cheap pre-filter eliminating distant pairs before refinement.
- **Refinement**: High-resolution recomputation of a candidate encounter.
- **Operational Risk Priority**: Orbital Guardian's explainable 0-100 event
  prioritization score. Not a collision probability.
- **Pc**: Probability of Collision; formal metric requiring covariance data.
- **Data freshness / confidence**: Measure of how old the underlying orbital
  elements are; older elements yield lower prediction confidence.
