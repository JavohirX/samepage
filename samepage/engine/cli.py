"""Print a snapshot for a fixture file. `python -m samepage.engine.cli fixtures.json`."""

from __future__ import annotations

import json
import sys

from samepage.engine.snapshot import build_snapshot


def load_counted(path: str) -> tuple[list[dict], dict, dict]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    projects = {row["id"]: row for row in payload["projects"]}
    # Provisional keep-latest: same team and (same repo or same folded title), drop the earlier row.
    groups: dict[tuple, list] = {}
    for row in payload["projects"]:
        key = (row["team"], row.get("repo_url") or row["title"].casefold())
        groups.setdefault(key, []).append(row)
    withdrawn = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda row: row.get("submitted_at") or "")
        for row in ordered[:-1]:
            withdrawn.add(row["id"])
    weights = {"functionality": 1, "quality": 1, "innovation": 1}
    reviews = []
    for score in payload["scores"]:
        if score["project"] in withdrawn:
            continue
        reviews.append(
            {
                "project_id": score["project"],
                "judge_id": score["judge"],
                "criteria": score["criteria"],
            }
        )
    meta = {
        row["id"]: {
            "title": row["title"],
            "track": row["track"],
            "submitted_at": row.get("submitted_at") or "",
        }
        for row in payload["projects"]
        if row["id"] not in withdrawn
    }
    return reviews, meta, weights


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "fixtures.json"
    reviews, meta, weights = load_counted(path)
    snapshot = build_snapshot(reviews, meta, weights, with_lojo=False)
    print(f"lambda {snapshot['lambda']:.4f}")
    print(f"loglik {snapshot['loglik']:.4f}")
    print(f"projects {snapshot['n_projects']} reviews {snapshot['n_reviews']}")
    print(f"kendall raw {snapshot['kendall_raw']:.4f}")
    print(f"top5 {' '.join(snapshot['top5'])}")
    print(f"ranking_sha256 {snapshot['ranking_sha256']}")
    print(f"dense gap {snapshot['dense_max_abs']:.3e}")
    print(f"banner {snapshot['banner']['text']}")
    for row in snapshot["rows"][:8]:
        print(
            f"#{row['rank']:>2} {row['id']} {row['title']:<16} "
            f"adj {row['adjusted_display']} raw {row['raw_display']} k10 {row['k10_display']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
