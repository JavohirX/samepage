# Data model

Ids are the fixture's text ids (`evt_01`, `prj_07`, `jdg_08`); rows created in the portal get a prefix and random hex (`evt_1a2b3c4d`, `tm_…`, `prj_…`, `per_…`). Times are `timestamptz`, UTC. Migrations are in `samepage/apps/portal/migrations/`; triggers are SQL in 0002 and 0004.

## Event

`event.state` is draft → open → closed → judging → published → archived (`domain/transitions.py`; only forward). `starts_at`, `submissions_close` and `judging_ends` are the windows; `submissions_close` is the deadline both the service and the triggers use. `max_team_size`, `blind_judging`, `description`, `created_by`. `custom_questions` is a JSON list of `{key, label, kind: text|choice, choices, required}`. `track` and `prize_category` belong to one event.

`criterion` is the rubric: `(event, track, key)` unique, `label`, `weight > 0` (numeric, 4 decimals), `position`. Rows with `track` null are the event's weights; a row with a track overrides that one weight for that track. evt_01 is seeded 1:1:1.

## People

`person` is the Django user (PBKDF2 password hash; unusable for fixture people and for invited people until they set one). `role_grant` is participant, judge or organizer on one event; `person.is_admin` is the global admin. `api_token` stores sha256, optional expiry, and a `demo` flag. `judge_track` is who may be assigned to a track. `coi` is an explicit conflict. A judge whose email is on the team is also excluded, even without a row.

`invite` is a secret link, stored as the sha256 of the token only:

- `kind = team`: joins `team`. `expires_at`, `max_uses`, `uses` (CHECK `uses <= max_uses`), `revoked_at`.
- `kind = password`: lets `person` choose a password once. Issuing a new one revokes the old.

A CHECK ties each kind to its target (`invite_target`).

## Teams

`team` belongs to one event. `team_member` is unique per (event, person): one team per person per event. Joining or starting a team grants `participant` on the event; leaving removes it. An empty team without a submission is deleted.

## Submissions

`submission` holds the standard fields: `title`, `tagline`, `description`, `thumbnail` (a media URL), `video_url`, `repo_url`, `live_url`, `tech_tags` (text[]), `track`, `custom_answers` (JSON keyed by question key). `state` is draft → submitted → (withdrawn); `version` counts edits. `origin` is `native` or `import`. The partial unique index `submission_one_active_native` allows one non-withdrawn native submission per team. Imported rows are outside that index, which is how Dry Harbour (two rows, one team) loads.

`submission_media` holds images: `kind` thumbnail or gallery, `position ≤ 6`, `sha256`, `content_type` (sniffed from the bytes), `size`, and the bytes themselves in `data`, so a `pg_dump` is the whole backup and the app needs no writable disk.

Triggers: `submission_deadline` refuses a native insert after `submissions_close` and refuses content updates after close (not `state`, `duplicate_group`, `withdrawn_reason` or `merged_into`). `submission_media_deadline` refuses adding or removing an image after close. Both honour a `deadline_exception` row. An import is refused only when its own `submitted_at` is after close.

## Judging

`assignment_run` is one run of the matcher or one manual assignment: `kind` import, initial, topup, dry_run or manual, with its seed, parameters and report. `batch` is one judge's work from one run (issued → in_progress → done, or abandoned). `assignment` is unique per (judge, submission) and records `finalized_at`.

`score_rev` is append-only. The current value is the view `score_current` (`DISTINCT ON (judge, submission, criterion) ORDER BY rev DESC`). States: draft, final, unlocked. A rev after a final rev must be an `unlocked` rev whose audit seq points at a `score.unlock` event (trigger `score_final_guard`); the organizer's unlock route writes exactly that. Identical autosaves do not insert. Concurrent saves for one assignment queue on a row lock.

`scores.csv` is one row per judge and project, with one `c_<key>` column per criterion and the weighted total with that track's weights. `counted` is true only when every criterion's current rev is final and the project is active (or merged into an active one). Otherwise `excluded_reason` says why: `not_final:draft`, `not_final:unlocked`, `withdrawn_duplicate:<group>`, or the withdrawal reason.

## Duplicates

`duplicate_group` is provisional or confirmed, resolution `keep_latest` or `merge`. Detection is same team and (same normalised repo or same case-folded title). The seed creates `dup_01` for prj_07 and prj_41, applies keep-latest, audits it, and leaves the status provisional. Publish checks that no group is still provisional; after publish a group cannot be switched.

## Audit

`audit_event` is append-only and hash-chained. Appends take `pg_advisory_xact_lock(hashtext(event))`. Every write in this document appends one: event create and update, rubric changes (with before and after), state moves, team create, join, leave and removal, invites, submissions, images, people added, password links, assignment runs, scores, unlocks, duplicate decisions and publish. `services/audit.py` verifies the chain and names the first broken seq.

## Results

`results_snapshot` stores the engine payload, `ranking_sha256` (sha256 of `project_id,rank\n` lines in rank order), the audit seq it reflects, and `input_fingerprint`: the sha256 of the counted reviews with their weights, the projects being ranked and the event's judges. Before publish, a read whose fingerprint no longer matches refits first, so results are never stale. Publish refits if needed, stamps `published_at` on that snapshot, and from then on every reader gets it. Judge flags in the payload: `straight_line` (one value on every criterion of every review), `no_total_variance` (equal weighted totals), `zero_counted`, `one_counted`, `at_most_two`, and `short_projects` (fewer than three counted reviews).

## Import and export

The importer is `services/seed.py` (fixtures.json, demo mode). Every list is also CSV and JSON on the same URL with a suffix.
