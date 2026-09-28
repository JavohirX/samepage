"""One payload, three renderers. Errors are plain Django responses, never DRF Responses."""

from __future__ import annotations

import csv
import io
import json

from django.http import HttpResponse
from django.shortcuts import render

from samepage.core.headers import annotate
from samepage.domain.csvguard import guard_cell

NUMERIC_HINTS = {
    "c_functionality",
    "c_quality",
    "c_innovation",
    "weighted_total",
    "audit_seq",
    "value",
    "rank",
    "rank_lo",
    "rank_hi",
    "n_reviews",
    "n",
    "position",
    "rev",
    "uses",
    "weight",
    "raw_mean",
    "adjusted",
    "raptors_k10",
    "p_top5",
    "track_rank",
    "lambda",
    "loglik",
}


def negotiate(request, explicit: str | None) -> str:
    if explicit:
        return explicit
    accept = request.META.get("HTTP_ACCEPT", "")
    if not accept or accept.strip() == "*/*":
        return "html"
    if "text/html" in accept:
        return "html"
    if "application/json" in accept or "application/problem+json" in accept:
        return "json"
    if "text/csv" in accept:
        return "csv"
    return "html"


def to_csv(payload: dict) -> str:
    items = payload.get("items") or []
    columns = list(payload.get("columns") or (list(items[0].keys()) if items else []))
    numeric = set(payload.get("numeric_columns") or ()) | (NUMERIC_HINTS & set(columns))
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for item in items:
        writer.writerow(guard_cell(item.get(column, ""), numeric=column in numeric) for column in columns)
    return buffer.getvalue()


def render_payload(request, payload: dict, fmt: str | None, *, template: str, status: int = 200, public_cache: bool = False):
    chosen = negotiate(request, fmt if fmt is not None else getattr(request, "samepage_fmt", None))
    if chosen == "json":
        body = json.dumps(payload, ensure_ascii=False, default=str)
        response = HttpResponse(body, status=status, content_type="application/json; charset=utf-8")
    elif chosen == "csv":
        response = HttpResponse(to_csv(payload), status=status, content_type="text/csv; charset=utf-8")
    else:
        from samepage.services.access import roles_of

        principal = getattr(request, "principal", None)
        if principal is None and getattr(request.user, "is_authenticated", False):
            principal = request.user
        roles = roles_of(principal, payload.get("event"))
        context = {
            "payload": payload,
            "columns": payload.get("columns") or [],
            "items": payload.get("items") or [],
            "omitted": payload.get("html_omitted") or {},
            "page_title": payload.get("title") or "Samepage",
            "event_id": payload.get("event"),
            "is_staff": bool(roles & {"organizer", "admin"}),
            "is_judge": "judge" in roles,
        }
        response = render(request, template, context, status=status)
    return annotate(response, request, fmt=fmt if fmt is not None else getattr(request, "samepage_fmt", None), public_cache=public_cache)
