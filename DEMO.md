# Demo

Open on the product. The progress page is the one-minute version. `docker compose up --wait` first.

1. Press **Organizer** in the demo bar. Progress reads "121 counted + 5 excluded = 126". Open the excluded link: five rows, all prj_07, reason `withdrawn_duplicate:dup_01`. The footer says the six numbers match the CSVs they link to, and it is recomputed from those CSVs on every load.
2. Open Duplicates, `dup_01`. Keep-latest puts prj_41 at rank 9. Merge retargets the withdrawn reviews and prints the other rank. Publish is refused (409) until the decision is confirmed.
3. Open the lab. λ is about 15.324. Z-scores are listed as failures where a judge has no usable variance, and the flags table names jdg_07 as the one straight-line judge. The limits at the bottom are part of the demo.
4. In a terminal: `docker compose --profile oracle run --rm oracle`. statsmodels gets the same λ and the same ranking hash as the results page.
5. Press **Judge B** and request `/e/evt_01/judges/jdg_08/scores.json`: 403. On a fresh volume the demo judges have only imported, finalized scores, so their console has nothing open to score (README, Limits). **Top up short projects** on the progress page can assign them a project, but it picks judges pseudo-randomly.
6. Sign out. As a stranger, `/e/evt_01/projects` shows Glass Signal first. `/e/evt_01/results` is 403 until an organizer publishes.

`python run.py .dogfood.toml` is the part that does not need a human. It ends in `claimed T1 T2, verified T1 T2`.

The password behind the sign-in form, if you would rather type it, is `samepage-demo`.
