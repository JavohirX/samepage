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

The weighted total is Σ wᵢ vᵢ / Σ wᵢ with every weight positive, computed with exact fractions. The organizer sets the weights per event, and may override them per track (settings page, or `POST /e/<event>/criteria.json`); each review uses the weights of its project's track. Criteria are fixed once the first score exists, because a review must score every criterion; weights can change until publish, each change is an audit event with before and after, and the next results read refits. On evt_01 the weights are 1:1:1, so the total is the mean of functionality, quality and innovation. The model is linear, so normalising the total is the same as weighting per-criterion normalised scores.

## What counts

A review counts when every criterion's current score is **final** and the project is active (or merged into an active project). A draft autosave, and a final score an organizer has reopened (unlocked), are in `scores.csv` with `counted=false` and `excluded_reason` `not_final:draft` or `not_final:unlocked`, and they are not in the fit. A judge finalizes from the console; a final score changes only after an organizer unlocks it (`POST /e/<event>/assignments/<judge>/<project>/unlock`, audited, and the database refuses any other way).

Each results snapshot records a fingerprint of its inputs: the counted reviews with their weights, the projects being ranked and the event's judges. Before publish, a read of the results or the lab whose fingerprint no longer matches refits first, so a new finalized score, a weight change or a duplicate decision is in the next page anyone sees. Publish refits if needed and stamps that snapshot; from then on every reader, signed in or not, gets exactly it, and the write paths that feed the ranking (scores, unlocks, weights, duplicate decisions, assignment runs, abandoning a batch) answer 409.

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

Every imported score is final. Dry Harbour is two submissions by one team (prj_07 at 04:29, prj_41 at 17:57 on the deadline day, same repo). The rule is explicit and written down in the data: same team and (same normalised repo or same case-folded title) forms a duplicate group; the default resolution is keep-latest; the importer applies it, writes a `duplicate.apply` audit event, and leaves the group **provisional**. Publish is refused until an organizer confirms keep-latest or switches to merge, which is another audit event; after publish it cannot be switched. Keep-latest withdraws prj_07 and keeps its five reviews in `scores.csv` with `counted=false`. That leaves 121 counted reviews and 40 projects.

On that set the engine reports:

- λ ≈ 15.324
- top 5: prj_34, prj_11, prj_25, prj_10, prj_37
- prj_41 (the kept Dry Harbour) at rank 9
- eight projects with fewer than three counted reviews: prj_10, prj_15, prj_18, prj_19, prj_24, prj_29, prj_39, prj_40

Switching the duplicate to merge retargets prj_07's five reviews onto prj_41, so three judges are in that project twice. The duplicates page prints the rank that fit produces. It is a preview, computed by the same function, not a stored slogan.

## When the model cannot be fitted

The fit needs reviews of the same project that disagree. If within every project all counted reviews give the same weighted total (one review per project, or a small event whose judges agree on everything), the residual after the project means is zero and the REML likelihood is undefined. The engine checks this on exact fractions before fitting, because in floating point the residual is rounding noise and a λ picked from it would mean nothing.

The results then say `method raw_fallback`. Each project's score is the mean of its counted weighted totals: the `weighted_total` column of `scores.csv`, so the organizer's weights (and any track override) apply exactly as in the fit. No judge's lean is removed. The order is that exact mean, then more reviews, then earlier submission, then id. The results page and `results.json` say so in `story` and `fallback_reason`, and the k=10, P(top-5) and rank-interval columns are empty. The same fallback is used if the fit fails, or takes longer than `SAMEPAGE_ENGINE_BOOT_BUDGET_S`. A weight change refits on the next read under either method (`tests/test_results_fallback.py` runs a 2-project, 2-judge event with 9:1 weights through it).

## Other columns

- **Raw mean.** The fraction mean of counted weighted totals.
- **Raptors k=10.** (n · raw + 10 · grand) / (n + 10), where grand is the mean of all counted weighted totals. This implements the Code Olympics formula. It does not claim to reproduce every published digit from that event.
- **Z-scores.** Per judge, (y − mean) / sd. Undefined when n < 2 or sd = 0. On this fixture that includes jdg_07 (4/4/4 on everything, sd 0) and the one-score judges (jdg_23; jdg_01 once merge counts its one Dry Harbour review). The lab shows z as a refused method, with the failure table as the reason. It is not the published ranking. Nothing divides by a zero standard deviation: the REML fit never uses a per-judge sd, and a judge with one review keeps most of their lean in the noise term.

## Flags

The lab lists judge flags from the counted reviews. Nothing flagged is dropped. `straight_line` is a judge who gave one value on every criterion of every review (jdg_07's 4/4/4). `no_total_variance` is a judge whose weighted totals are all equal, which is also true of jdg_19 (3/5/3, 3/4/4 and 5/4/2 all total 11/3) without being a straight line. `zero_counted` is a judge on the event with no counted review (jdg_01 scored only the withdrawn Dry Harbour row).

## Checked by statsmodels

`tools/oracle_statsmodels.py` (README, check 3) fits statsmodels' MixedLM to the portal's `scores.csv`, evaluates its REML likelihood on this grid and compares λ, every adjusted score, every rank and `ranking_sha256` with `results.json`. On the fixture both sides give λ = 15.32391847910442 and the same ranking hash.

## Uncertainty

4,000 draws of a ~ N(â, σ̂² (Xᵀ H⁻¹ X)⁻¹), conditional on λ̂. The page says the uncertainty in λ is ignored. It reports a 90% rank interval and P(top-5). The banner names the lowest rank whose project still has P(top-5) ≥ 0.10. On this fixture that band is wide: no top-5 slot is settled.

Leave-one-judge-out refits the grid once per counted judge (29 on the fixture) and names the judges whose removal changes the top-5 set.

## What this does not prove

- A grand mean can beat every shrinkage method at predicting a held-out score when the project signal is this small.
- The model assumes Gaussian additive bias. Halo and ceiling effects are not in it.
- Intervals are conditional on the chosen λ.
- The published order is a documented estimator, not a claim that the top of the table is statistically separated.

## Assignment

Issuing batches, the dry run and top-up use the same matcher: repeated maximum bipartite matchings. An edge exists only when the judge is eligible for the track, has no conflict of interest, has not already reviewed the project, and is under the load cap. Each round uses a judge at most once. Projects and judges are sorted by id before the seeded shuffle, so the same inputs and seed issue the same pairs.

- **Issue batches** (`kind=initial`): every submitted project gets reviewers until it has `coverage` (default 3), counting assignments that already exist; `cap` (default 12) is the most any judge carries. Drafts and withdrawn projects are never assigned.
- **Top up** (`kind=topup`): projects with fewer than three active assignments get one more reviewer each, at most one extra per judge. Unfinished assignments in an abandoned batch do not count, so that work goes to someone else, and the judge of an abandoned batch gets no new work from a run.
- **Assign one** (`POST /e/<event>/assignments.json {judge, project}`): the same rules, checked one by one: 409 for another track, a conflict of interest, a project that is not submitted, or a pair that exists.
- **Dry run**: a fresh design that ignores existing reviews and issues nothing.

Judges are invited by email on the settings page with the tracks they judge (none ticked means all). A new address gets an account and a one-time set-password link. An address that already has an account gets a one-time acceptance link instead, and becomes a judge only when that account, signed in, accepts it: anyone can sign up with any address, so an existing account is not proof of who holds it. Until then the people list shows the invitation as not accepted, and the matcher does not see them. 'Judging ends', if set, is enforced: after it, saving and finalizing a score answer 409 until an organizer moves it later. The judging context is track-scoped: a judge is assigned, opens in the console, and scores only projects in their tracks, and reads only their own scores. The public gallery stays public to everyone, judges included.

The run report prints the load histogram, coverage, component count, articulation judges, the seed, the number of assigned pairs that break a conflict rule (measured from the pairs, not assumed), and a hand-checkable lower bound: a track with 6 projects and 3 eligible judges needs someone at load at least 6 for coverage 3, and a connected design needs at least 7. When the reviews do not divide evenly among the eligible judges, the connected bound equals the first bound, because a judge below it can take the bridging review. Dry runs and top-ups are written to the audit chain. The imported fixture is not that design. It is the fixture's own reviews, max load 11, and we do not invent a batch history for it. The dry-run button computes a fresh design without issuing it.

## Scores CSV

Columns: `id, judge_id, project_id, track`, one `c_<key>` per criterion in rubric order (on evt_01 `c_functionality, c_quality, c_innovation`), then `weighted_total, comment, state, counted, excluded_reason, merged_into, audit_seq`.

Empty comments are empty strings. `counted` is `true` or `false`. The file does not contain the literal `null`. Text cells that start with `= + - @`, tab or carriage return get a leading quote. Numeric columns do not.
