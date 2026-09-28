"""Repeated maximum bipartite matchings. One algorithm for the initial design and for top-up.

Each round pairs projects that still need reviews with eligible judges, and uses each judge at most once.
The load cap is the most rounds a judge can be picked. Coverage is how many reviews each project is aiming for.
"""

from __future__ import annotations

import random
from collections import defaultdict


def maximum_matching(left: list[str], edges: dict[str, list[str]]) -> dict[str, str]:
    match_right: dict[str, str] = {}

    def dfs(node: str, seen: set[str]) -> bool:
        for other in edges.get(node, []):
            if other in seen:
                continue
            seen.add(other)
            if other not in match_right or dfs(match_right[other], seen):
                match_right[other] = node
                return True
        return False

    for node in left:
        dfs(node, set())
    return {left_id: right_id for right_id, left_id in match_right.items()}


def assign(
    projects: list[dict],
    judges: list[dict],
    *,
    existing: set[tuple[str, str]] | None = None,
    cap: int = 12,
    coverage: int = 3,
    seed: int = 1,
    abandoned: set[str] | None = None,
    extra_per_judge: int | None = None,
) -> dict:
    """projects: {id, track}. judges: {id, tracks: list, email}.

    extra_per_judge, when set, limits how many NEW assignments each judge may take
    (top-up uses 1). The cap still applies to total load.
    """
    existing = set(existing or ())
    abandoned = set(abandoned or ())
    rng = random.Random(seed)
    project_ids = [row["id"] for row in projects]
    judge_ids = [row["id"] for row in judges]
    rng.shuffle(project_ids)
    rng.shuffle(judge_ids)
    track_of = {row["id"]: row["track"] for row in projects}
    tracks_of = {row["id"]: set(row.get("tracks") or []) for row in judges}
    emails = {row["id"]: (row.get("email") or "").lower() for row in judges}
    team_emails = {row["id"]: {e.lower() for e in row.get("team_emails") or []} for row in projects}
    coi = {(row["id"], c) for row in judges for c in row.get("coi_teams") or []}
    team_of = {row["id"]: row.get("team") for row in projects}

    load = {judge: 0 for judge in judge_ids}
    have = {project: 0 for project in project_ids}
    for project, judge in existing:
        if judge in load:
            load[judge] += 1
        if project in have:
            have[project] += 1
    fresh: list[tuple[str, str]] = []
    taken_new = {judge: 0 for judge in judge_ids}

    for _round in range(cap):
        need = [project for project in project_ids if have[project] < coverage]
        if not need:
            break
        edges: dict[str, list[str]] = {}
        for project in need:
            options = []
            for judge in judge_ids:
                if judge in abandoned:
                    continue
                if load[judge] >= cap:
                    continue
                if extra_per_judge is not None and taken_new[judge] >= extra_per_judge:
                    continue
                if (project, judge) in existing or (project, judge) in fresh:
                    continue
                if track_of[project] not in tracks_of[judge]:
                    continue
                if emails[judge] and emails[judge] in team_emails[project]:
                    continue
                if (judge, team_of[project]) in coi:
                    continue
                options.append(judge)
            edges[project] = options
        matching = maximum_matching(need, edges)
        if not matching:
            break
        for project, judge in matching.items():
            fresh.append((project, judge))
            load[judge] += 1
            have[project] += 1
            taken_new[judge] += 1

    histogram: dict[str, int] = defaultdict(int)
    for judge, count in load.items():
        histogram[str(count)] += 1
    covered = sum(1 for project in project_ids if have[project] >= coverage)
    return {
        "assignments": [{"project_id": project, "judge_id": judge} for project, judge in fresh],
        "load": load,
        "coverage_count": have,
        "achieved_max_load": max(load.values()) if load else 0,
        "covered": covered,
        "projects": len(project_ids),
        "load_histogram": dict(sorted(histogram.items(), key=lambda item: int(item[0]))),
        "seed": seed,
        "cap": cap,
        "coverage": coverage,
    }


def graph_report(edges: list[tuple[str, str]]) -> dict:
    """Connected components and articulation judges of the judge–project graph."""
    adj: dict[str, set[str]] = defaultdict(set)
    judges = set()
    projects = set()
    for project, judge in edges:
        p_node, j_node = f"p:{project}", f"j:{judge}"
        adj[p_node].add(j_node)
        adj[j_node].add(p_node)
        projects.add(p_node)
        judges.add(j_node)
    seen = set()
    components = 0
    for node in list(adj):
        if node in seen:
            continue
        components += 1
        stack = [node]
        seen.add(node)
        while stack:
            current = stack.pop()
            for nxt in adj[current]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    # Isolated judges or projects are their own components; callers pass only edges,
    # so isolated people are not counted. The report says so.
    articulation = _articulation_judges(adj)
    return {
        "components": components,
        "articulation_judges": sorted(articulation),
        "note": "Components count nodes that appear in at least one review edge.",
    }


def _articulation_judges(adj: dict[str, set[str]]) -> list[str]:
    time = 0
    disc: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    cuts: set[str] = set()

    def dfs(node: str) -> None:
        nonlocal time
        disc[node] = low[node] = time
        time += 1
        children = 0
        for nxt in sorted(adj[node]):
            if nxt not in disc:
                parent[nxt] = node
                children += 1
                dfs(nxt)
                low[node] = min(low[node], low[nxt])
                if parent.get(node) is None and children > 1:
                    cuts.add(node)
                if parent.get(node) is not None and low[nxt] >= disc[node]:
                    cuts.add(node)
            elif nxt != parent.get(node):
                low[node] = min(low[node], disc[nxt])

    for node in sorted(adj):
        if node not in disc:
            parent[node] = None
            dfs(node)
    return [node[2:] for node in cuts if node.startswith("j:")]


def lower_bound(projects: list[dict], judges: list[dict], coverage: int = 3) -> dict:
    """Hand-checkable load bound. No solver."""
    by_track: dict[str, list[str]] = defaultdict(list)
    for row in projects:
        by_track[row["track"]].append(row["id"])
    eligible: dict[str, list[str]] = {}
    for track in by_track:
        eligible[track] = sorted(
            judge["id"] for judge in judges if track in set(judge.get("tracks") or [])
        )
    lines = []
    force = []
    for track in sorted(by_track):
        n = len(by_track[track])
        k = len(eligible[track])
        if k == 0:
            lines.append(f"{track}: {n} projects, 0 eligible judges, coverage {coverage} is impossible")
            continue
        at_least = (coverage * n + k - 1) // k
        lines.append(
            f"{track}: {n} projects, {k} eligible ({', '.join(eligible[track])}), "
            f"coverage {coverage} forces some judge to carry at least {at_least}"
        )
        # Judges eligible only for this track are the only bridge out of it.
        outsiders = [
            judge
            for judge in eligible[track]
            if set(next(j["tracks"] for j in judges if j["id"] == judge)) <= {track}
        ]
        if outsiders and len(by_track) > 1:
            force.append(
                f"{track}: any review linking it to another track must be done by "
                f"{', '.join(eligible[track])}. A connected design needs some judge with load ≥ {at_least + 1}."
            )
    return {"lines": lines, "connected": force, "coverage": coverage}
