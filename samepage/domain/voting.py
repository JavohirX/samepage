"""Pure domain logic for community voting: balanced rotation and quadratic arithmetic.

Must remain free of Django and external database/web frameworks (import-linter contract).
"""

from __future__ import annotations

import decimal
import math
from typing import Any, Sequence, TypeVar

T = TypeVar("T")

# Exact precision for influence calculation (4 decimal places formatted)
INFLUENCE_DECIMALS = 4


def balanced_rotation(items: Sequence[T], sequence_number: int) -> list[T]:
    """Balanced rotation (Latin-square rotation).

    Voter number i sees the list rotated by i, so across voters every item appears
    in every position equally often. Stable on reload for the same sequence_number.
    """
    if not items:
        return []
    n = len(items)
    offset = sequence_number % n
    return list(items[offset:]) + list(items[:offset])


def quadratic_influence(credits_spent: int) -> decimal.Decimal:
    """Compute the influence from integer credits spent on one project.

    The spec: 'casting n votes costs sqrt(n) influence' / c credits yields sqrt(c) influence.
    Using exact decimal arithmetic with fixed precision.
    """
    if credits_spent <= 0:
        return decimal.Decimal("0.0000")
    # decimal context with sufficient precision
    with decimal.localcontext() as ctx:
        ctx.prec = 28
        val = decimal.Decimal(credits_spent).sqrt()
        # Quantize to 4 decimal places
        return val.quantize(decimal.Decimal("0.0001"), rounding=decimal.ROUND_HALF_UP)


def compute_tallies(
    ballots: Sequence[dict[str, Any]],
    project_ids: Sequence[str],
) -> dict[str, Any]:
    """Compute voting tallies separated by channel: participants and public, plus combined.

    ballots: list of dicts with:
      - 'id': str
      - 'channel': 'participants' | 'public'
      - 'excluded': bool
      - 'votes': dict[project_id, credits]

    Returns dict with:
      - 'participants': list of project tally dicts sorted by influence desc, id asc
      - 'public': list of project tally dicts sorted by influence desc, id asc
      - 'combined': list of project tally dicts sorted by influence desc, id asc
      - 'ballot_counts': {'total': int, 'counted': int, 'excluded': int, 'participants': int, 'public': int}
    """
    # Initialize trackers
    data = {
        "participants": {pid: {"credits": 0, "influence": decimal.Decimal(0), "voters": 0} for pid in project_ids},
        "public": {pid: {"credits": 0, "influence": decimal.Decimal(0), "voters": 0} for pid in project_ids},
        "combined": {pid: {"credits": 0, "influence": decimal.Decimal(0), "voters": 0} for pid in project_ids},
    }

    counts = {
        "total": len(ballots),
        "counted": 0,
        "excluded": 0,
        "participants": 0,
        "public": 0,
    }

    for b in ballots:
        if b.get("excluded"):
            counts["excluded"] += 1
            continue

        counts["counted"] += 1
        ch = b.get("channel", "public")
        if ch == "participants":
            counts["participants"] += 1
        else:
            counts["public"] += 1

        votes = b.get("votes", {})
        for pid, cr in votes.items():
            if pid not in data["combined"] or cr <= 0:
                continue
            inf = quadratic_influence(cr)

            # Combined
            data["combined"][pid]["credits"] += cr
            data["combined"][pid]["influence"] += inf
            data["combined"][pid]["voters"] += 1

            # Channel
            if ch in data:
                data[ch][pid]["credits"] += cr
                data[ch][pid]["influence"] += inf
                data[ch][pid]["voters"] += 1

    def format_list(channel_data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for pid in project_ids:
            item = channel_data.get(pid, {"credits": 0, "influence": decimal.Decimal(0), "voters": 0})
            inf_dec = item["influence"].quantize(decimal.Decimal("0.0001"), rounding=decimal.ROUND_HALF_UP)
            result.append({
                "project_id": pid,
                "credits": item["credits"],
                "influence": str(inf_dec),
                "influence_num": float(inf_dec),
                "voters": item["voters"],
            })
        # Sort by influence desc, then project_id asc for deterministic tie-break
        result.sort(key=lambda x: (-x["influence_num"], x["project_id"]))
        for rank, row in enumerate(result, 1):
            row["rank"] = rank
        return result

    return {
        "participants": format_list(data["participants"]),
        "public": format_list(data["public"]),
        "combined": format_list(data["combined"]),
        "ballot_counts": counts,
    }
