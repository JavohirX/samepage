# Demo

`docker compose up --wait`, then open http://localhost:8080. Every step below is a real request to the portal; the buttons in the demo bar are POSTs that sign the browser in as that account.

## A whole event in five minutes

1. **Create the event.** Press **Admin**, open the home page, **New event**. Name, a deadline a few minutes from now (UTC), two tracks, a prize, a rubric such as `Impact: 2` and `Craft: 1`, and a required question `License: MIT, Apache-2.0*`. You land on the event's settings page. Press **Move to open**.
2. **Form a team.** Sign out, **Sign in**, then **Create one** (sign-up). On the event page press **Start a team**. On the team page press **Create an invite link** and copy it. In a private window, sign up a second person and open the link: **Join**.
3. **Submit.** Back as the first person: **Start the submission**, fill the fields, leave "Submit now" unticked. The draft is not in the gallery. **Edit** it, add a thumbnail under Images, answer the license question, then **Submit**. It is now in the gallery; search for a tag to find it.
4. **Invite judges.** As Admin, on the settings page under *Judges and organizers*, add a judge by email. The next page shows a one-time set-password link; open it in another private window and choose a password.
5. **The deadline.** Wait for it to pass. An edit is now refused with "submissions closed at …" (and a trigger refuses it in the database too). On the settings page: **Move to closed**, **Move to judging**. On Progress: **Issue batches**.
6. **Judge.** As the judge: the console lists the batch. Score with keys 1–5 (J/K move between criteria) or the form, **Save draft**, then **Finalize**. A draft is not counted; only finalized reviews enter the fit. Asking for another judge's `/judges/<id>/scores.json` is 403.
7. **Weights and progress.** As Admin, change a weight on the settings page: `scores.csv` shows the new weighted totals and the results refit on the next read. Progress lists judges with open work first.
8. **Publish.** Results → **Publish results**. Sign out: the results page is now public, and it is frozen: a late finalize, a weight change or a new assignment is 409.

`python tools/lifecycle_check.py --admin-email admin@example.org` (with `SAMEPAGE_ADMIN_PASSWORD=samepage-demo`) does steps 1–8 over HTTP in about a minute and prints every request.

## The fixture (evt_01)

1. Press **Organizer**. Progress reads "121 counted + 5 excluded = 126". Open the excluded link: five rows, all prj_07, reason `withdrawn_duplicate:dup_01`. The footer says the six numbers match the CSVs they link to, recomputed from those CSVs on every load.
2. Open Duplicates, `dup_01`. The rule is "same team and (same repo or same title)"; keep-latest puts prj_41 at rank 9, merge retargets the withdrawn reviews and prints the other rank. Publish is refused (409) until a person confirms it.
3. Open the lab. λ is about 15.324. Z-scores are listed as failures where a judge has no usable variance (jdg_07 gave 4/4/4 to everything; jdg_23 has one review), and the flags table names jdg_07 as the one straight-line judge.
4. In a terminal: `docker compose --profile oracle run --rm oracle`. statsmodels gets the same λ and the same ranking hash as the results page.
5. Press **Judge A**. The console has two open projects (the demo seed's `run_demo` batch). Finalize one; the organizer's results now count it. As **Judge B**, `/e/evt_01/judges/jdg_08/scores.json` is 403.
6. As a stranger, `/e/evt_01/projects` shows Glass Signal, Small Meadow and Deep Compass first. `/e/evt_01/results` is 403 until an organizer publishes.

`python run.py .dogfood.toml` is the part that does not need a human. It ends in `claimed T1 T2, verified T1 T2`.
