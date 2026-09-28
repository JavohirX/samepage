"""Container healthcheck: GET /healthz on the local port with a Host the app accepts.

Production mode answers 400 to a Host outside ALLOWED_HOSTS, so the probe sends the first
allowed host instead of 127.0.0.1. Exit 0 when the portal answers 200.
"""

from __future__ import annotations

import http.client
import os
import sys


def main() -> int:
    hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost").split(",") if h.strip()]
    host = next((h.lstrip(".") for h in hosts if h != "*"), "localhost")
    port = os.environ.get("BIND", "0.0.0.0:8000").rpartition(":")[2] or "8000"
    connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=3)
    try:
        connection.request("GET", "/healthz", headers={"Host": host})
        status = connection.getresponse().status
    except OSError as exc:
        print(f"healthcheck: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    if status != 200:
        print(f"healthcheck: /healthz answered {status} for Host {host}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
