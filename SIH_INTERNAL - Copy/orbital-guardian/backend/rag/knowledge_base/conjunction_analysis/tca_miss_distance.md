# Time of Closest Approach (TCA)

The Time of Closest Approach is the instant during which two orbiting objects
reach their minimum separation distance within an analysis window.

## How Orbital Guardian computes TCA

1. Coarse search: both trajectories are sampled at the configured step size
   and the minimum sampled separation is located.
2. Refinement: SGP4 propagates both objects at fine steps around the coarse
   estimate to locate the true local minimum of separation.

Both stages are fully deterministic.

## Miss Distance

The miss distance (minimum separation) is the Euclidean distance between the
two object positions at TCA, computed in kilometres from SGP4 state vectors.

## Relative Velocity

Relative velocity at TCA is the magnitude of the difference of the two
velocity vectors. LEO crossing encounters are typically 7–15 km/s.

## Uncertainty

Because TLEs carry positional errors that grow after epoch, the computed TCA
and miss distance inherit uncertainty. A small predicted miss distance does
not imply a collision will occur; conversely large distances make events
operationally irrelevant. Formal conjunction assessment additionally uses
covariance data, which public TLEs do not provide.
