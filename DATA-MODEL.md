# Data model

Ids are the fixture's text ids (`evt_01`, `prj_07`, `jdg_08`). Times are `timestamptz`, UTC.

## Event

`event.state` is draft → open → closed → judging → published → archived. `submissions_close` is the deadline. Criteria live on `criterion` with `weight > 0`. evt_01 is seeded 1:1:1.

## People

`person` is the Django user. `role_grant` is participant, judge or organizer on one event. Admins have `is_admin`. `api_token` stores sha256, optional expiry, and a `demo` flag. `judge_track` is who may be assigned to a track. `coi` is an explicit conflict. A judge whose email is on the team is also excluded, even without a row.

## Submissions

`origin` is `native` or `import`. The partial unique index `submission_one_active_native` allows one non-withdrawn native submission per team. Imported rows are outside that index, which is how Dry Harbour (two rows, one team) loads.

A trigger refuses a native insert after `submissions_close`, and refuses content updates after close. It does not block changes to `state`, `duplicate_group`, `withdrawn_reason` or `merged_into`. An import is refused only when its own `submitted_at` is after close.

## Scores

`score_rev` is append-only. The current value is the view `score_current` (`DISTINCT ON (judge, submission, criterion) ORDER BY rev DESC`). A new rev after a final rev must be an `unlocked` rev whose audit seq points at `score.unlock`. Identical autosaves do not insert.

`scores.csv` is one row per judge and project, with the three criterion columns beside it. `counted` is false when the project was withdrawn as a duplicate and not merged.

## Duplicates

`duplicate_group` is provisional or confirmed, resolution `keep_latest` or `merge`. Detection is same team and (same normalised repo or same case-folded title). The seed creates `dup_01` for prj_07 and prj_41, applies keep-latest, and leaves the status provisional. Publish checks that no group is still provisional.

## Audit

`audit_event` is append-only and hash-chained. Appends take `pg_advisory_xact_lock(hashtext(event))`. `services/audit.py` verifies the chain and names the first broken seq.

## Results

`results_snapshot` stores the engine payload and `ranking_sha256` (sha256 of `project_id,rank\n` lines in rank order). A new snapshot is written when a duplicate decision is confirmed.
