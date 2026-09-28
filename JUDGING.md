# Judging

The default method is an additive judge-bias model fit by profile REML. Raw means and the Raptors k=10 shrinkage are columns beside it, not hidden alternatives.

## Model

Each counted review is the project's quality, plus that judge's lean, plus noise:

- y = X a + Z b + e
- a is a fixed effect, one per project
- b ~ N(0, τ²), one lean per judge
- e ~ N(0, σ²)
- λ = σ² / τ²

A large λ means most of what looks like a harsh or generous judge is noise, so little of it is removed. A judge with one score keeps most of it, because one score is not evidence of a lean.

The weighted total is Σ wᵢ vᵢ / Σ wᵢ with every weight positive, computed with exact fractions. On evt_01 the weights are 1:1:1, so the total is the mean of functionality, quality and innovation. The model is linear, so normalising the total is the same as weighting per-criterion normalised scores.

## The grid is part of the method

Let t = ln λ.

- Stage 1: t = ln 0.1 + 0.05·k for k = 0..184 (185 points).
- Stage 2: t₁ + 0.001·m for m = −50..50, where t₁ is the stage-1 maximiser.

That is 286 evaluations. If two points tie, the earlier one wins. A maximiser on the edge of stage 1 is flagged. The likelihood on this fixture is flat, which is why a library's default optimiser is not the method: it can stop early and still look converged.

Profile log-likelihood, up to a constant that does not depend on λ:

ℓ(g) = −½ [ (N − P) log σ̂² + log|H| + log|Xᵀ H⁻¹ X| ]

with g = 1/λ, H = I + g Z Zᵀ, and σ̂² = rᵀ H⁻¹ r / (N − P). Each review has one judge, so ZᵀZ is diagonal and the Woodbury form is exact. `engine/reml.py` is that form. A dense inverse of V is the differential test and agrees to about 1e-15 on the fixture.

The adjusted score is â, the GLS project effect at λ̂, shown to 3 decimal places. Rank uses full precision, then P(top-5), then more reviews, then earlier submission.

## What the fixture does

Counted rows are the reviews whose project is still active. The importer's default, keep-latest, withdraws prj_07 (the earlier Dry Harbour) and keeps its five reviews in `scores.csv` with `counted=false`. That leaves 121 counted reviews and 40 projects.

On that set the engine reports:

- λ ≈ 15.324
- top 5: prj_34, prj_11, prj_25, prj_10, prj_37
- prj_41 (the kept Dry Harbour) at rank 9
- eight projects with fewer than three counted reviews: prj_10, prj_15, prj_18, prj_19, prj_24, prj_29, prj_39, prj_40

Switching the duplicate to merge retargets prj_07's five reviews onto prj_41, so three judges are in that project twice. The duplicates page prints the rank that fit produces. It is a preview, computed by the same function, not a stored slogan.

## Other columns

- **Raw mean.** The fraction mean of counted weighted totals.
- **Raptors k=10.** (n · raw + 10 · grand) / (n + 10), where grand is the mean of all counted weighted totals. This implements the Code Olympics formula. It does not claim to reproduce every published digit from that event.
- **Z-scores.** Per judge, (y − mean) / sd. Undefined when n < 2 or sd = 0. On this fixture that includes jdg_07 (straight line) and the one-score judges. The lab shows z as a refused method, with the failure table as the reason. It is not the published ranking.

## Uncertainty

4,000 draws of a ~ N(â, σ̂² (Xᵀ H⁻¹ X)⁻¹), conditional on λ̂. The page says the uncertainty in λ is ignored. It reports a 90% rank interval and P(top-5). The banner names the lowest rank whose project still has P(top-5) ≥ 0.10. On this fixture that band is wide: no top-5 slot is settled.

Leave-one-judge-out refits the grid 30 times and names the judges whose removal changes the top-5 set.

## What this does not prove

- A grand mean can beat every shrinkage method at predicting a held-out score when the project signal is this small.
- The model assumes Gaussian additive bias. Halo and ceiling effects are not in it.
- Intervals are conditional on the chosen λ.
- The published order is a documented estimator, not a claim that the top of the table is statistically separated.

## Assignment

Initial batches and top-up use the same matcher: repeated maximum bipartite matchings. An edge exists only when the judge is eligible for the track, has no conflict of interest, has not already reviewed the project, and is under the load cap (12 by default). Each round uses a judge at most once. Top-up adds at most one extra review per judge.

The run report prints the load histogram, coverage, component count, articulation judges, the seed, and a hand-checkable lower bound: a track with 6 projects and 3 eligible judges needs someone at load at least 6 for coverage 3, and a connected design needs at least 7. The imported fixture is not that design. It is the fixture's own reviews, max load 11, and we do not invent a batch history for it. The dry-run button computes a fresh design without issuing it.

## Scores CSV

Columns, frozen: `id, judge_id, project_id, track, c_functionality, c_quality, c_innovation, weighted_total, comment, state, counted, excluded_reason, merged_into, audit_seq`.

Empty comments are empty strings. `counted` is `true` or `false`. The file does not contain the literal `null`. Text cells that start with `= + - @`, tab or carriage return get a leading quote. Numeric columns do not.
