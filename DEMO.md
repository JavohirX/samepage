# Demo

Open on the product. The progress page is the one-minute version.

1. http://localhost:8080/demo/enter/org lands on progress. Read "121 counted + 5 excluded = 126". Open the excluded link. Five rows, all prj_07, reason `withdrawn_duplicate:dup_01`.
2. Open duplicates, `dup_01`. Keep-latest puts prj_41 at rank 9. Merge retargets the withdrawn reviews and prints the other rank. Leave it on keep-latest, or confirm it. Publish is refused until that confirmation.
3. Open the lab. λ is about 15.324. Z-scores are listed as failures where a judge has no variance. The limits at the bottom are part of the demo, not a footnote to skip.
4. Sign in as Judge A and open a batch. Score with the keyboard or the form. Judge B's request for `/e/evt_01/judges/jdg_08/scores.json` is 403.
5. As a stranger, `/e/evt_01/projects` shows Glass Signal first. `/e/evt_01/results` is 403 until an organizer publishes.

`python run.py .dogfood.toml` is the part that does not need a human. It should end in `verified T1 T2`.

The password behind the form, if you would rather not use the demo links, is `samepage-demo`.
