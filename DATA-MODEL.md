# Data model

Postgres 16. The schema is in `samepage/apps/portal/models.py` and `samepage/apps/portal/migrations/`; the triggers and the `score_current` view are SQL in migrations 0002 and 0004. Ids are the fixture's text ids (`evt_01`, `prj_07`, `jdg_08`); rows created in the portal get a prefix and random hex (`evt_1a2b3c4d`, `tm_…`, `prj_…`, `per_…`, `inv_…`, `run_…`, `bat_…`). Times are `timestamptz`, shown in UTC.

## Relationships

```
event ─┬─ track
       ├─ prize_category (optionally for one track)
       ├─ criterion (event weights; a row with a track overrides one weight for that track)
       ├─ role_grant ─── person ─── api_token
       │    └─ judge_track (which tracks a judge may be assigned)
       ├─ team ─── team_member ─── person
       │    └─ submission ─── submission_media
       │          └─ duplicate_group (optional), merged_into (optional, another submission)
       ├─ invite (team link, set-password link or role offer)
       ├─ assignment_run ─── batch (one judge) ─── assignment (judge × submission)
       ├─ score_rev (judge × submission × criterion × rev; append-only) → view score_current
       ├─ audit_event (append-only, hash-chained per event)
       └─ results_snapshot
```

## Event

`event.state` is draft → open → closed → judging → published → archived (`domain/transitions.py`; only forward, and `published` only through publish). `starts_at`, `submissions_close` and `judging_ends` are the windows; `submissions_close` is the deadline the service and the triggers both use, and the event cannot move to `closed` before it. `judging_ends`, when set, is checked by the service on every score save and finalize (409 after it, on the database clock); an organizer can move it later until publish. Also `max_team_size` (1 to 20, default 4), `blind_judging`, `description`, `created_by`. `custom_questions` is a JSON list of `{key, label, kind: text|choice, choices, required}`, at most 20. `track` and `prize_category` belong to one event (at most 30 tracks).

`criterion` is the rubric: `(event, track, key)` unique, `label`, `weight` (numeric, 4 decimals, CHECK `> 0`; the service also caps it at 1000), `position`. Rows with `track` null are the event's weights; a row with a track overrides that one weight for that track. 1 to 10 criteria, scored 1 to 5. evt_01 is seeded functionality, quality and innovation at 1:1:1.

## People

`person` is the Django user: email (unique, lower-cased), name, `is_admin` (global admin), `is_active`, and a PBKDF2 password hash, unusable for fixture people and for invited people until they set one. `role_grant` is participant, judge or organizer on one event (CHECK on the role, unique per person, event and role). `api_token` stores the sha256 of a bearer token, an optional expiry, a revoked time and a `demo` flag; only the demo seed writes it. `judge_track` is which tracks a judge may be assigned. `coi` is a declared conflict between a judge and a team; the matcher honours it, but no route writes it (an operator adds one with SQL). A judge whose email is on the team is excluded even without a row.

`invite` is a secret link, stored as the sha256 of the token only:

- `kind = team`: joins `team`. `expires_at` (1 to 30 days, default 7), `max_uses` (1 to 20, default 3), `uses` (CHECK `uses <= max_uses`), `revoked_at`.
- `kind = password`: lets `person` choose a password once, within 14 days. Issuing a new one revokes the old.
- `kind = role`: offers an existing `person` the `role` (judge or organizer) on `event`, with the judge's `tracks`. One use, 14 days; a new offer of the same role revokes an unused one. The `role_grant` row is written when that person, signed in, accepts; until then they hold nothing.

A CHECK (`invite_target`) ties each kind to its target.

## Teams

`team` belongs to one event. `team_member` is unique per (event, person): one team per person per event. Joining or starting a team grants `participant` on the event; leaving removes it. An empty team without a submission is deleted with its invites. The last member cannot leave while the team has an active submission.

## Submissions

`submission` holds the standard fields: `title`, `tagline`, `description`, `thumbnail` (the URL of its thumbnail image), `video_url`, `repo_url`, `live_url`, `tech_tags` (text[]), `track`, `custom_answers` (JSON keyed by question key), and `position` (gallery order). `state` is draft → submitted, and either can become withdrawn (`withdrawn_reason`); `locked` is allowed by the CHECK but nothing sets it. `version` counts edits. `origin` is `native` or `import`. The partial unique index `submission_one_active_native` allows one non-withdrawn native submission per team. Imported rows are outside that index, which is how Dry Harbour (two rows, one team) loads.

`submission_media` holds images: `kind` thumbnail or gallery (CHECK), `position` (CHECK `<= 6`; the thumbnail is 0), `sha256`, `content_type` (sniffed from the bytes), `size`, and the bytes themselves in `data`, so a `pg_dump` is the whole backup and the app needs no writable disk.

Triggers:

- `submission_deadline` refuses a native insert after `submissions_close`, and refuses a change to any content column (title, tagline, description, thumbnail, the three URLs, tags, answers, track) after it. `state`, `duplicate_group`, `withdrawn_reason` and `merged_into` may still change, so withdrawals and duplicate decisions work after the deadline. An import is refused only when its own `submitted_at` is after close.
- `submission_media_deadline` refuses adding, changing or removing an image after close.

Both let a content change or an image change through while a `deadline_exception` row for that submission is in force (`until` in the future). No route writes that table; it exists for an operator's extension granted with SQL.

## Judging

`assignment_run` is one run of the matcher or one manual assignment: `kind` import, initial, topup, dry_run or manual, with its seed, parameters and report (a dry run's report holds its design and the lower bound; nothing is issued). `batch` is one judge's work from one run: issued → in_progress → done, or abandoned. `assignment` is unique per (judge, submission), records its `source` and `finalized_at`.

`score_rev` is append-only (trigger `score_rev_append_only` refuses UPDATE and DELETE; the runtime role also lacks the grants). A value is 1 to 5 (CHECK). The current value is the view `score_current` (`DISTINCT ON (judge, submission, criterion) ORDER BY rev DESC`). States: draft, final, unlocked. A rev after a final rev must be an `unlocked` rev whose `audit_seq` points at a `score.unlock` audit event (trigger `score_final_guard`); the organizer's unlock route writes exactly that. Identical autosaves do not insert. Concurrent saves for one assignment queue on a row lock.

`scores.csv` is one row per judge and project: `id, judge_id, project_id, track`, one `c_<key>` column per criterion, then `weighted_total` (with that track's weights), `comment, state, counted, excluded_reason, merged_into, audit_seq`. `counted` is true only when every criterion's current rev is final and the project is active or merged into an active one. Otherwise `excluded_reason` says why: `not_final:draft`, `not_final:unlocked`, `withdrawn_duplicate:<group>`, `incomplete_rubric`, or the withdrawal reason.

## Duplicates

`duplicate_group`: `rule`, `members` (text[]), `resolution` keep_latest or merge, `status` provisional or confirmed, `resolved_by`, `audit_seq`. The importer detects groups (same team and same normalised repo, or same team and same case-folded title); native submissions cannot form one, because of the one-active-submission index. The seed creates `dup_01` for prj_07 and prj_41, applies keep-latest, audits it, and leaves it provisional. Keep-latest withdraws the earlier row with `withdrawn_reason = duplicate_of:<kept>`; merge sets `merged_into`, so its reviews count toward the kept project. Publish refuses while any group is provisional; after publish a group cannot be confirmed or switched.

## Audit

`audit_event` is append-only and hash-chained per event: each row stores the previous row's hash and the sha256 of its own canonical JSON (actor, action, object, before, after, previous hash). Appends take `pg_advisory_xact_lock(hashtext(event))`, so each event's chain has one writer at a time. Every write to an event appends one: event create and update, rubric changes (with before and after), state moves, team create, join, leave and removal, invite create and revoke, submission create, update, submit and withdraw, image add and remove, people added or invited, role acceptance, set-password links issued and used, assignment runs (initial, top-up, manual, dry run), abandoned batches, scores (draft and final), unlocks, duplicate decisions and publish. Account writes outside an event (sign-up, a password change) are not in it. `services/audit.py` verifies the chain and names the first broken seq; `/e/<event>/audit` shows the result.

## Results

`results_snapshot` stores the engine payload, `method` (`reml` or `raw_fallback`), `ranking_sha256` (sha256 of `project_id,rank\n` lines in rank order), the audit seq it reflects, how long the fit took, and `input_fingerprint`: the sha256 of the counted reviews with their weights, the projects being ranked and the event's judges. Before publish, a read whose fingerprint no longer matches refits first, so results are never stale. Publish refits if needed, stamps `published_at` on that snapshot, and from then on every reader gets it. Judge flags in the payload: `straight_line` (one value on every criterion of every review), `no_total_variance` (equal weighted totals), `zero_counted`, `one_counted`, `at_most_two`, and `short_projects` (fewer than three counted reviews).

Also in the schema: `samepage_cache` (the sign-in throttle's counter, migration 0003) and `normalization_run` (from the first migration, unused).

## Import and export

- Import: `services/seed.py` loads `fixtures.json` in demo mode. In production, `POST /e/import.json` (admin only) accepts portable event bundles (a strict superset of `fixtures.json`), validating the schema, mapping foreign keys and slugs, detecting duplicates, and executing inside an atomic transaction.
- Export: every list is also CSV and JSON on the same URL with a suffix (`/e/evt_01/scores.csv`, `/e/evt_01/projects.json`, …). `GET /e/<event>/export.json` produces the complete, portable event bundle for migration or archival. CSV text cells that start with `= + - @`, a tab or a carriage return get a leading quote; numeric columns do not; empty values are empty, never `null`.
- Whole database: `docker compose --profile ops run --rm backup` writes a `pg_dump -Fc` that includes the images ([OPERATIONS.md](OPERATIONS.md#backup)).

## Package T3 & T4 Extensions

- **Community Voting (T3)**: `voting_config` (enabled, credit budget, participant weight multiplier, voter eligibility), `ballot` (one ballot per voter, quadratic credits allocation), `voting_tally` (audited tally snapshot: participants, public, and combined quadratic influence ranks), `mail_outbox` (dev-mode magic link inbox).
- **Public Comments (T3)**: `project_comment` (project, author, body, state: pending → approved / rejected).
- **Signed Records (T4)**: `signed_root` (event, publish_seq, Merkle root hash, leaf count, Ed25519 signature, public key PEM, statement), `judge_protocol` (judge evaluation protocol with RFC 9162 Merkle inclusion proofs).
- **Certificates (T4)**: `team_certificate` (team, certificate number, award title, is_winner, payload sha256, Ed25519 signature, public key PEM, self-contained SVG content).
- **Feedback (T4)**: `feedback_release` (audited release gate linking organizer release action to audit log seq).
- **Webhooks (T4)**: `webhook_endpoint` (event, target URL, secret, active), `webhook_delivery` (Standard Webhooks v1 HMAC-SHA256 signature, payload, timestamp, status, delivery attempts).
