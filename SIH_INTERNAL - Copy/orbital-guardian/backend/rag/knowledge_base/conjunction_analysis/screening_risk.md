# Screening and Risk Prioritization

## Broad-phase screening

Screening every pair of objects precisely is expensive. Orbital Guardian
first compares sampled trajectory points and only refines pairs whose
sampled minimum distance falls below a configurable threshold (default 25 km).
This threshold is a computational filter, not a danger boundary.

## Operational Risk Priority

Orbital Guardian ranks flagged events with an explainable weighted score
(0–100) called Operational Risk Priority. Factors:

| Factor             | Weight | Meaning                                  |
|--------------------|--------|------------------------------------------|
| Miss distance      | 50%    | Closer approaches rank higher            |
| Relative velocity  | 20%    | Faster closing rates rank higher         |
| Time urgency       | 20%    | Imminent TCAs rank higher                |
| Object criticality | 10%    | Debris involvement raises attention      |

Levels: CRITICAL (>=80), HIGH (>=60), MEDIUM (>=30), LOW (<30).

## NOT probability of collision

Operational Risk Priority is a screening/prioritization heuristic. It is not
a Probability of Collision (Pc). Computing Pc requires covariance matrices
and hard-body radii that public TLEs do not contain.

## Data confidence

Confidence reflects element-set freshness: predictions based on recent TLEs
are more trustworthy. Confidence is reported separately from risk so users
can weigh both dimensions independently.
