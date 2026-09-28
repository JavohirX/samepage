"""Snapshots, the lab, and publish. The CSV ledger does not wait on this module.

A snapshot records the fingerprint of its inputs (counted reviews with their weights, the
projects being ranked, the event's judges). Before publish, a read whose fingerprint no
longer matches refits first, so the ranking is never stale. Publish stamps one snapshot;
from then on every reader gets that snapshot, and the write paths refuse changes (guards.py).
"""

from __future__ import annotations

import hashlib
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from samepage.apps.portal.models import AuditEvent, Event, Person, ResultsSnapshot, RoleGrant
from samepage.core.errors import Conflict
from samepage.domain.canonical import canonical
from samepage.engine.snapshot import build_snapshot
from samepage.services import audit
from samepage.services.guards import FROZEN
from samepage.services.ledger import counted_for_engine, weights_for


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def latest(event_id: str) -> ResultsSnapshot | None:
    return ResultsSnapshot.objects.filter(event_id=event_id).order_by("-seq").first()


def _inputs(event_id: str) -> tuple[list[dict], dict, dict, list[str], str]:
    reviews, meta = counted_for_engine(event_id)
    weights = weights_for(event_id)
    # Every judge on the event, so a judge with no counted review is flagged rather than invisible.
    present = sorted(
        RoleGrant.objects.filter(event_id=event_id, role="judge").values_list("person_id", flat=True)
    )
    material = {
        "reviews": sorted(
            [
                review["project_id"],
                review["judge_id"],
                sorted(review["criteria"].items()),
                sorted((review.get("weights") or weights).items()),
            ]
            for review in reviews
        ),
        "projects": sorted([key, value.get("track", ""), value.get("submitted_at", "")] for key, value in meta.items()),
        "weights": sorted(weights.items()),
        "judges": present,
    }
    fingerprint = hashlib.sha256(canonical(material).encode("utf-8")).hexdigest()
    return reviews, meta, weights, present, fingerprint


def fingerprint(event_id: str) -> str:
    return _inputs(event_id)[4]


def rebuild(event_id: str, *, actor: str = "engine", cause: int | None = None) -> ResultsSnapshot:
    started = time.perf_counter()
    budget = settings.ENGINE_BOOT_BUDGET_S
    previous = latest(event_id)
    seq = 1 if previous is None else previous.seq + 1
    reviews, meta, weights, present, digest = _inputs(event_id)
    if cause is None:
        # The snapshot reflects the audit log up to this row.
        cause = AuditEvent.objects.filter(event_id=event_id).order_by("-seq").values_list("seq", flat=True).first()
    method = "reml"
    payload: dict
    if budget <= 0:
        payload = _fallback(reviews, meta, "budget is 0")
        method = "raw_fallback"
    else:
        try:
            snapshot = build_snapshot(
                reviews, meta, weights, with_lojo=True, with_draws=True, judges_present=present
            )
            if time.perf_counter() - started > budget:
                payload = _fallback(reviews, meta, "over budget")
                method = "raw_fallback"
            else:
                payload = snapshot
                method = snapshot.get("method") or "reml"
        except Exception as exc:
            payload = _fallback(reviews, meta, exc.__class__.__name__)
            method = "raw_fallback"
    seconds = round(time.perf_counter() - started, 3)
    payload = _jsonable(payload)
    payload["seconds"] = seconds
    row = ResultsSnapshot.objects.create(
        event_id=event_id,
        seq=seq,
        method=method,
        ranking_sha256=payload.get("ranking_sha256") or "",
        payload=payload,
        cause_audit_seq=cause,
        seconds=seconds,
        input_fingerprint=digest,
    )
    return row


def published_snapshot(event_id: str) -> ResultsSnapshot | None:
    return (
        ResultsSnapshot.objects.filter(event_id=event_id, published_at__isnull=False).order_by("-seq").first()
    )


def fresh(event_id: str) -> ResultsSnapshot:
    """The latest snapshot, refitted first if its inputs changed since it was built."""
    snapshot = latest(event_id)
    if snapshot is not None and snapshot.input_fingerprint == fingerprint(event_id):
        return snapshot
    with transaction.atomic():
        # One refit at a time per event; a second reader waits here and then finds it fresh.
        Event.objects.select_for_update().filter(id=event_id).first()
        snapshot = latest(event_id)
        if snapshot is not None and snapshot.input_fingerprint == fingerprint(event_id):
            return snapshot
        return rebuild(event_id)


def current(event_id: str) -> ResultsSnapshot | None:
    """What a reader sees: the published snapshot once published, else a fresh one."""
    state = Event.objects.filter(id=event_id).values_list("state", flat=True).first()
    if state is None:
        raise NotFound("Unknown event.")
    if state in FROZEN:
        return published_snapshot(event_id) or latest(event_id)
    return fresh(event_id)


def _fallback(reviews, meta, reason: str) -> dict:
    from collections import defaultdict

    totals = defaultdict(list)
    for review in reviews:
        values = list(review["criteria"].values())
        if not values:
            continue
        totals[review["project_id"]].append(sum(values) / len(values))
    rows = []
    for project, values in totals.items():
        info = meta.get(project, {})
        rows.append(
            {
                "id": project,
                "title": info.get("title", ""),
                "track": info.get("track", ""),
                "submitted_at": info.get("submitted_at", ""),
                "raw_mean": sum(values) / len(values),
                "n_reviews": len(values),
                "adjusted": sum(values) / len(values),
                "raptors_k10": None,
                "p_top5": None,
                "rank_lo": None,
                "rank_hi": None,
                "z_mean": None,
                "z_rank": None,
                "flags": "",
            }
        )
    rows.sort(key=lambda row: (-row["raw_mean"], row["submitted_at"], row["id"]))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row["raw_rank"] = index
        row["k10_rank"] = None
        row["adjusted_display"] = f"{row['adjusted']:.3f}"
        row["raw_display"] = f"{row['raw_mean']:.3f}"
        row["k10_display"] = ""
        row["p_top5_display"] = ""
        row["tie_group"] = index
        row["track_rank"] = ""
        row["rank_move_raw"] = 0
    from samepage.domain.canonical import ranking_sha256

    return {
        "method": "raw_fallback",
        "reason": reason,
        "rows": rows,
        "ranking_sha256": ranking_sha256([(row["id"], row["rank"]) for row in rows]),
        "banner": {"m": None, "text": "normalization unavailable: raw means, ranks provisional"},
        "top5": [row["id"] for row in rows[:5]],
        "ablation": {},
        "z_failures": [],
        "sensitivity": [],
        "lojo": [],
        "flags": {},
        "lambda": None,
        "loglik": None,
    }


def _rows(event_id: str) -> tuple[ResultsSnapshot | None, list[dict]]:
    snapshot = current(event_id)
    if snapshot is None:
        return None, []
    return snapshot, list(snapshot.payload.get("rows") or [])


def results_payload(event_id: str) -> dict:
    snapshot, rows = _rows(event_id)
    payload = snapshot.payload if snapshot else {}
    short = set((payload.get("flags") or {}).get("short_projects") or [])
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "title": row.get("title", ""),
                "rank": row.get("rank"),
                "rank_lo": row.get("rank_lo") or "",
                "rank_hi": row.get("rank_hi") or "",
                "adjusted": row.get("adjusted_display", ""),
                "raw_mean": row.get("raw_display", ""),
                "raptors_k10": row.get("k10_display", ""),
                "n_reviews": row.get("n_reviews"),
                "p_top5": row.get("p_top5_display", ""),
                "tie_group": row.get("tie_group") or "",
                "track_rank": row.get("track_rank") or "",
                "track": row.get("track", ""),
                "method": (snapshot.method if snapshot else ""),
                "flags": "short" if row["id"] in short else "",
            }
        )
    story = (
        "Each project's score is the average of its judges' weighted rubric scores "
        "after removing each judge's measured lean, with judges who scored few projects trusted less; "
        "the Raptors k=10 and raw columns are shown beside it."
    )
    return {
        "title": "Results",
        "event": event_id,
        "resource": "results",
        "method": snapshot.method if snapshot else "missing",
        "lambda": payload.get("lambda"),
        "ranking_sha256": payload.get("ranking_sha256", ""),
        "banner": (payload.get("banner") or {}).get("text", ""),
        "story": story,
        "degraded": snapshot.method == "raw_fallback" if snapshot else True,
        "columns": [
            "id",
            "title",
            "rank",
            "rank_lo",
            "rank_hi",
            "adjusted",
            "raw_mean",
            "raptors_k10",
            "n_reviews",
            "p_top5",
            "tie_group",
            "track_rank",
            "track",
            "method",
            "flags",
        ],
        "items": items,
        "count": len(items),
        "download_csv": f"/e/{event_id}/results.csv",
        "download_json": f"/e/{event_id}/results.json",
        "html_omitted": {"flags": "short (fewer than 3 counted reviews) is in the CSV and JSON; judge flags are on the lab page"},
        "published": Event.objects.filter(id=event_id, state__in=FROZEN).exists(),
        "published_at": snapshot.published_at.strftime("%Y-%m-%dT%H:%M:%SZ") if snapshot and snapshot.published_at else "",
        "snapshot_seq": snapshot.seq if snapshot else "",
        "reflects_audit_seq": snapshot.cause_audit_seq if snapshot else "",
        "open_duplicates": list(
            Event.objects.get(id=event_id).duplicates.filter(status="provisional").values_list("id", flat=True)
        ),
    }


def lab_payload(event_id: str, table: str | None = None) -> dict:
    snapshot = current(event_id)
    payload = snapshot.payload if snapshot else {}
    rows = list(payload.get("rows") or [])
    ablation_items = []
    for row in rows:
        ablation_items.append(
            {
                "id": row["id"],
                "title": row.get("title", ""),
                "raw_rank": row.get("raw_rank"),
                "z_rank": row.get("z_rank") or "",
                "reml_rank": row.get("rank"),
                "k10_rank": row.get("k10_rank"),
                "rank_move_raw": row.get("rank_move_raw"),
            }
        )
    z_items = []
    for row in payload.get("z_failures") or []:
        z_items.append(
            {
                "judge_id": row.get("judge_id"),
                "n": row.get("n"),
                "sd": "" if row.get("sd") is None else row.get("sd"),
                "reason": row.get("reason"),
            }
        )
    interval_items = [
        {
            "id": row["id"],
            "rank": row.get("rank"),
            "rank_lo": row.get("rank_lo") or "",
            "rank_hi": row.get("rank_hi") or "",
            "p_top5": row.get("p_top5_display", ""),
        }
        for row in rows
    ]
    sensitivity = []
    for row in payload.get("sensitivity") or []:
        sensitivity.append(
            {
                "lambda": row.get("lambda"),
                "loglik": row.get("loglik"),
                "top5": " ".join(row.get("top5") or []),
                "top5_same": "true" if row.get("top5_same") else "false",
                "is_hat": "true" if row.get("is_hat") else "false",
            }
        )
    lojo = [
        {
            "judge_id": row.get("judge_id"),
            "top5_changed": "" if row.get("top5_changed") is None else ("true" if row.get("top5_changed") else "false"),
            "top5": " ".join(row.get("top5") or []),
        }
        for row in payload.get("lojo") or []
    ]
    tables = {
        "ablation": {"columns": ["id", "title", "raw_rank", "z_rank", "reml_rank", "k10_rank", "rank_move_raw"], "items": ablation_items},
        "z-failures": {"columns": ["judge_id", "n", "sd", "reason"], "items": z_items},
        "intervals": {"columns": ["id", "rank", "rank_lo", "rank_hi", "p_top5"], "items": interval_items},
        "sensitivity": {"columns": ["lambda", "loglik", "top5", "top5_same", "is_hat"], "items": sensitivity},
        "lojo": {"columns": ["judge_id", "top5_changed", "top5"], "items": lojo},
    }
    if table:
        if table not in tables:
            raise NotFound("Unknown lab table.")
        chosen = tables[table]
        return {
            "title": table,
            "event": event_id,
            "resource": f"normalization/{table}",
            "columns": chosen["columns"],
            "items": chosen["items"],
            "count": len(chosen["items"]),
            "lambda": payload.get("lambda"),
            "ablation_summary": payload.get("ablation") or {},
            "download_csv": f"/e/{event_id}/normalization/{table}.csv",
            "download_json": f"/e/{event_id}/normalization/{table}.json",
            "html_omitted": {},
        }
    limits = [
        "In leave-one-score-out prediction, a grand mean can beat every method on this flat fixture. The lab does not claim the model is the right one.",
        "The model assumes Gaussian additive judge bias.",
        "Halo and ceiling effects are not modelled.",
        "Rank intervals are conditional on the chosen λ. Uncertainty in λ itself is ignored.",
        "Nothing here proves a top-5 slot is settled. Read the tie banner on the results page.",
    ]
    return {
        "title": "Normalization lab",
        "event": event_id,
        "resource": "normalization",
        "lambda": payload.get("lambda"),
        "loglik": payload.get("loglik"),
        "kendall_raw": payload.get("kendall_raw"),
        "icc": payload.get("icc"),
        "k_data": payload.get("k_data"),
        "banner": (payload.get("banner") or {}).get("text", ""),
        "ablation_summary": payload.get("ablation") or {},
        "tables": list(tables),
        "columns": ["id", "title", "raw_rank", "z_rank", "reml_rank", "k10_rank", "rank_move_raw"],
        "items": ablation_items,
        "z_failures": z_items,
        "intervals": interval_items,
        "sensitivity": sensitivity,
        "lojo": lojo,
        "limits": limits,
        "flags": payload.get("flags") or {},
        "flag_rows": [
            {"flag": key, "who": " ".join(value)}
            for key, value in sorted((payload.get("flags") or {}).items())
        ],
        "count": len(ablation_items),
        "download_csv": f"/e/{event_id}/normalization/ablation.csv",
        "download_json": f"/e/{event_id}/normalization.json",
        "html_omitted": {},
        "method": snapshot.method if snapshot else "missing",
    }


@transaction.atomic
def publish(event_id: str, actor: Person) -> Event:
    event = Event.objects.select_for_update().filter(id=event_id).first()
    if event is None:
        raise NotFound("Unknown event.")
    open_dups = list(event.duplicates.filter(status="provisional").values_list("id", flat=True))
    if open_dups:
        names = ", ".join(open_dups)
        raise Conflict(f"{len(open_dups)} provisional decision ({names}) must be confirmed before publishing")
    if event.state in FROZEN:
        return event
    from samepage.domain.transitions import transition

    transition("event", event.state, "published")
    # The ranking that goes public is fitted on the inputs as they are now, not a stale one.
    snapshot = fresh(event_id)
    event.state = "published"
    event.save(update_fields=["state"])
    audit.append(
        event_id,
        actor.id,
        "results.publish",
        event_id,
        {"state": "judging"},
        {"state": "published", "snapshot_seq": snapshot.seq, "ranking_sha256": snapshot.ranking_sha256},
    )
    snapshot.published_at = timezone.now()
    snapshot.save(update_fields=["published_at"])
    return event
