#!/usr/bin/env python3
"""Make every committed receipt from a real command, and nothing else. Standard library only.

    python tools/verify.py inputs            sha256 of run.py and fixtures.json -> receipts/inputs.txt
    python tools/verify.py stack             against a running demo portal (docker compose up --wait):
                                             run.py -> acceptance-report.txt, the tests -> receipts/tests.txt,
                                             the statsmodels oracle -> receipts/oracle-statsmodels.txt,
                                             then run.py again, which must print the same report
    python tools/verify.py backup            Docker, demo stack up: the documented backup and restore
                                             commands, with a change in between that the restore undoes
                                             -> receipts/backup-restore.txt
    python tools/verify.py production        Docker: production mode refuses a demo-seeded volume, boots on
                                             a fresh one, an operator runs one event over HTTP, and readiness
                                             says 503 with the database stopped -> receipts/production-*.txt,
                                             receipts/readiness-db-down.txt. It ends with 'docker compose down -v'.
    python tools/verify.py fetch [--run ID]  copies those files from a green CI run of this commit (gh) and
                                             writes receipts/ci-run.txt

CI (.github/workflows/acceptance.yml) runs stack, backup and production, and uploads what they
write. The committed receipts are that output, copied by `fetch`, which refuses a run that is not
green or that ran on code other than the code in this checkout. Each step exits 1 on the first
check that fails and says which.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / "receipts"
TOML = ROOT / ".dogfood.toml"
VERDICT = re.compile(r"^claimed (?P<claimed>.*), verified (?P<verified>.*)$", re.M)
CLAIMED_VERDICT = "claimed T1 T2, verified T1 T2"


class Failed(Exception):
    pass


def lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(lf(text).encode("utf-8"))
    print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return path


def run(args: list[str], *, env: dict | None = None, merge: bool = True, timeout: int = 1800, stdin: str | None = None):
    """(exit code, output). merge=False keeps stderr out of the output and prints it instead."""
    child = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
    try:
        proc = subprocess.run(
            args,
            cwd=ROOT,
            env=child,
            input=stdin.encode() if stdin is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge else subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return 127, f"{exc}\n"
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.output or b"").decode("utf-8", "replace") + f"\ntimed out after {timeout} s\n"
    output = proc.stdout.decode("utf-8", "replace")
    if not merge and proc.stderr:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
    return proc.returncode, lf(output)


def must(code: int, output: str, what: str) -> str:
    if code != 0:
        print(output[-4000:])
        raise Failed(f"{what} exited {code}")
    return output


def toml_value(section: str, key: str) -> str:
    current = None
    for raw in TOML.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
        elif current == section and line.startswith(key):
            name, _, value = line.partition("=")
            if name.strip() == key:
                return value.strip().strip('"')
    raise Failed(f".dogfood.toml has no {section}.{key}")


def header(line: str) -> dict:
    name, _, value = line.partition(":")
    return {name.strip(): value.strip()}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def http(method: str, url: str, *, headers: dict | None = None, body: dict | None = None, timeout: int = 30):
    """(status, content type, body bytes). No redirect is followed; 4xx and 5xx are answers, not errors."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return 0, "", str(exc).encode()


def wait_healthy(base: str, seconds: int = 300) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if http("GET", base + "/healthz", timeout=5)[0] == 200:
            return
        time.sleep(1)
    raise Failed(f"{base}/healthz did not answer 200 within {seconds} s")


def checker(toml: Path) -> str:
    code, output = run([sys.executable, "run.py", str(toml)], merge=False, timeout=600)
    found = VERDICT.search(output)
    if code != 0 or not found or found.group(0) != CLAIMED_VERDICT:
        print(output)
        raise Failed(f"run.py did not end with '{CLAIMED_VERDICT}' (exit {code})")
    return output


def toml_for(base: str, directory: Path) -> Path:
    """.dogfood.toml, pointed at base when it is not the portal the file names."""
    text = TOML.read_text(encoding="utf-8")
    if base.rstrip("/") == toml_value("portal", "base_url").rstrip("/"):
        return Path(".dogfood.toml")  # relative to ROOT, where every command runs
    text, count = re.subn(r'(?m)^base_url = ".*"$', f'base_url = "{base}"', text)
    if count != 1:
        raise Failed(".dogfood.toml has no single base_url line")
    path = directory / "dogfood.toml"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


# --- inputs ----------------------------------------------------------------------------------


def cmd_inputs(_args) -> None:
    lines = [f"{name} {hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}" for name in ("run.py", "fixtures.json")]
    write(RECEIPTS / "inputs.txt", "\n".join(lines) + "\n")


# --- stack -----------------------------------------------------------------------------------


def cmd_stack(args) -> None:
    base = (args.base_url or toml_value("portal", "base_url")).rstrip("/")
    wait_healthy(base)
    with tempfile.TemporaryDirectory() as scratch:
        toml = toml_for(base, Path(scratch))
        report = checker(toml)
        write(ROOT / "acceptance-report.txt", report)

        if args.tests == "docker":
            code, output = run(["docker", "compose", "--profile", "test", "run", "--rm", "test"], merge=False, timeout=1800)
        elif args.tests == "native":
            code, output = run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rs"], timeout=1800)
        else:
            code, output = 0, ""
        if args.tests != "skip":
            write(RECEIPTS / "tests.txt", output)
            summary = [line for line in output.splitlines() if re.match(r"^=*\s*\d+ passed", line)]
            print("tests:", summary[-1] if summary else "no summary line")
            must(code, output, "the test suite")
            if not summary or "failed" in summary[-1] or "error" in summary[-1]:
                raise Failed("the test suite printed no clean 'N passed' line")

        if args.oracle == "docker":
            code, output = run(["docker", "compose", "--profile", "oracle", "run", "--rm", "oracle"], merge=False)
        elif args.oracle == "native":
            code, output = run([sys.executable, "tools/oracle_statsmodels.py", "--toml", str(toml)], merge=False)
        else:
            code, output = 0, ""
        if args.oracle != "skip":
            write(RECEIPTS / "oracle-statsmodels.txt", output)
            must(code, output, "the statsmodels oracle")
            if not re.search(r"(?m)^PASS", output):
                raise Failed("the oracle did not print PASS")

        again = checker(toml)
        if again != report:
            raise Failed("run.py printed a different report after the tests and the oracle")
    print(f"stack: {CLAIMED_VERDICT}, twice; tests {args.tests}; oracle {args.oracle}")


# --- backup and restore ----------------------------------------------------------------------


def _ledger(base: str, org: dict) -> tuple[str, int, str, str]:
    status, _, csv_body = http("GET", base + "/e/evt_01/scores.csv", headers=org)
    if status != 200:
        raise Failed(f"scores.csv answered {status}")
    _, _, audit_body = http("GET", base + "/e/evt_01/audit.json", headers=org)
    audit = json.loads(audit_body)
    _, _, dup_body = http("GET", base + "/e/evt_01/duplicates/dup_01.json", headers=org)
    dup = json.loads(dup_body)
    return hashlib.sha256(csv_body).hexdigest(), audit["count"], audit["chain_ok"], f"{dup['status']} {dup['resolution']}"


def cmd_backup(args) -> None:
    base = (args.base_url or toml_value("portal", "base_url")).rstrip("/")
    wait_healthy(base)
    org = header(toml_value("auth", "organizer"))
    lines = ["backup and restore on the demo stack (docker compose --profile ops)"]

    def state(label: str) -> tuple:
        sha, count, chain, dup = _ledger(base, org)
        lines.append(f"{label}: scores.csv sha256 {sha[:16]}, audit events {count}, chain_ok {chain}, dup_01 {dup}")
        return sha, count, chain, dup

    before = state("before the backup")
    must(*run(["docker", "compose", "--profile", "ops", "run", "--rm", "backup"]), "docker compose --profile ops run --rm backup")
    lines.append("docker compose --profile ops run --rm backup -> exit 0")
    status, _, _ = http("POST", base + "/e/evt_01/duplicates/dup_01/confirm.json", headers=org, body={"resolution": "merge"})
    lines.append(f"POST /e/evt_01/duplicates/dup_01/confirm.json merge -> {status}")
    changed = state("after the change")
    if status != 200 or changed[0] == before[0] or changed[3] == before[3]:
        raise Failed("the change between backup and restore did not change the ledger")
    must(*run(["docker", "compose", "--profile", "ops", "run", "--rm", "restore"]), "docker compose --profile ops run --rm restore")
    lines.append("docker compose --profile ops run --rm restore -> exit 0")
    after = state("after the restore")
    if after != before:
        raise Failed(f"the restore did not bring back the backed-up state: {before} != {after}")
    lines.append("PASS: the restore brought back the backed-up scores, audit chain and duplicate decision")
    with tempfile.TemporaryDirectory() as scratch:
        report = checker(toml_for(base, Path(scratch)))
    lines.append("run.py after the restore: " + VERDICT.search(report).group(0))
    write(RECEIPTS / "backup-restore.txt", "\n".join(lines) + "\n")


# --- production mode -------------------------------------------------------------------------


def compose(*args: str, env: dict, timeout: int = 900) -> tuple[int, str]:
    return run(["docker", "compose", *args], env=env, timeout=timeout)


def cmd_production(args) -> None:
    base = "http://localhost:8080"
    secrets_env = {
        "SECRET_KEY": secrets.token_hex(32),
        "DB_OWNER_PASSWORD": secrets.token_hex(16),
        "DB_APP_PASSWORD": secrets.token_hex(16),
    }
    demo = dict(secrets_env, SAMEPAGE_MODE="demo")
    production = dict(secrets_env, SAMEPAGE_MODE="production", ALLOWED_HOSTS="localhost,127.0.0.1")
    try:
        must(*compose("build", "app", env=demo), "docker compose build")

        # 1. A volume seeded in demo mode is refused, and the refusal leaves the runtime role alone.
        must(*compose("up", "-d", "--wait", "--wait-timeout", "300", env=demo), "demo boot")
        must(*compose("stop", "app", env=demo), "docker compose stop app")

        def role_hash() -> str:
            # SCRAM salts every ALTER ROLE ... PASSWORD, so any change to the role shows as a new hash.
            code, out = run(
                ["docker", "compose", "exec", "-T", "db", "psql", "-U", "owner", "-d", "samepage", "-tAc",
                 "SELECT md5(rolpassword) FROM pg_authid WHERE rolname = 'samepage_app'"],
                env=demo, merge=False,
            )
            must(code, out, "reading samepage_app's password hash")
            return out.strip()

        before = role_hash()
        code, refusal = compose(
            "run", "--rm", "--no-deps", "-e", "SAMEPAGE_MODE=production", "-e", "ALLOWED_HOSTS=localhost", "app", env=demo
        )
        write(RECEIPTS / "production-refusal-demo-db.txt", refusal)
        if code == 0 or "demo bearer token" not in refusal or "demo password" not in refusal:
            raise Failed("production mode did not refuse the demo-seeded volume for its tokens and password")
        if not before or role_hash() != before:
            raise Failed("the refused boot changed samepage_app")
        print("The refused boot left samepage_app and its password untouched.")

        # 2. A fresh volume boots in production mode and refuses every demo credential.
        must(*compose("down", "-v", env=demo), "docker compose down -v")
        must(*compose("up", "-d", "--wait", "--wait-timeout", "300", env=production), "production boot")
        _, logs = compose("logs", "--no-color", "app", env=production)
        preflight = next((line for line in logs.splitlines() if "preflight passed" in line), "")
        org = header(toml_value("auth", "organizer"))
        checks = [
            ("GET /healthz", http("GET", base + "/healthz")[0], 200),
            ("GET /", http("GET", base + "/")[0], 200),
            ("GET /demo/enter/org", http("GET", base + "/demo/enter/org")[0], 404),
            ("GET /e/evt_01/scores.csv with the demo organizer token", http("GET", base + "/e/evt_01/scores.csv", headers=org)[0], 401),
        ]
        lines = ["production mode on a fresh volume", preflight]
        lines += [f"{label} -> {got}" for label, got, _want in checks]
        write(RECEIPTS / "production-mode.txt", "\n".join(lines) + "\n")
        if not preflight or any(got != want for _label, got, want in checks):
            raise Failed("production mode on a fresh volume did not answer as expected")

        # 3. The first admin by the documented command, then one whole event over HTTP only.
        password = secrets.token_hex(16)
        code, made = compose(
            "exec", "-T", "-e", "SAMEPAGE_ADMIN_PASSWORD", "app",
            "python", "manage.py", "samepage_admin", "--email", "ops@example.org", "--name", "Ops",
            env=dict(production, SAMEPAGE_ADMIN_PASSWORD=password),
        )
        code2, lifecycle = run(
            [sys.executable, "tools/lifecycle_check.py", "--base", base, "--admin-email", "ops@example.org"],
            env={"SAMEPAGE_ADMIN_PASSWORD": password}, timeout=900,
        )
        text = "production mode, fresh volume: manage.py samepage_admin, then tools/lifecycle_check.py\n" + made + lifecycle
        write(RECEIPTS / "production-lifecycle.txt", text)
        if code != 0 or "created admin" not in made:
            raise Failed("manage.py samepage_admin failed")
        if code2 != 0 or not re.search(r"(?m)^lifecycle PASS", lifecycle):
            raise Failed("tools/lifecycle_check.py failed")

        # 4. With the database stopped: liveness 200, readiness 503, an API URL a 500 problem document.
        must(*compose("stop", "db", env=production), "docker compose stop db")
        rows = [
            ("GET /healthz", http("GET", base + "/healthz"), "200"),
            ("GET /readyz.json", http("GET", base + "/readyz.json"), "503 application/problem+json"),
            ("GET /e/evt_01/projects.json", http("GET", base + "/e/evt_01/projects.json"), "500 application/problem+json"),
        ]
        lines = ["production mode, database container stopped"]
        for label, (status, content_type, _body), _want in rows:
            lines.append(f"{label} -> {status}" + (f" {content_type}" if label != "GET /healthz" else ""))
        write(RECEIPTS / "readiness-db-down.txt", "\n".join(lines) + "\n")
        for (label, _answer, want), line in zip(rows, lines[1:]):
            if not line.startswith(f"{label} -> {want}"):
                raise Failed(f"{line} (wanted {want})")
    finally:
        _, logs = compose("logs", "--no-color", "--timestamps", env=production)
        (ROOT / "compose-production.log").write_bytes(logs.encode("utf-8"))
        compose("down", "-v", env=production)
    print("production: refusal, fresh boot, lifecycle and readiness all as expected")


# --- fetch from CI ---------------------------------------------------------------------------

# artifact/file in the CI run -> committed path
FROM_CI = {
    "acceptance-amd64/acceptance-report.txt": "acceptance-report.txt",
    "acceptance-amd64/receipts/tests.txt": "receipts/tests.txt",
    "acceptance-amd64/receipts/oracle-statsmodels.txt": "receipts/oracle-statsmodels.txt",
    "acceptance-amd64/receipts/backup-restore.txt": "receipts/backup-restore.txt",
    "production-mode/receipts/production-refusal-demo-db.txt": "receipts/production-refusal-demo-db.txt",
    "production-mode/receipts/production-mode.txt": "receipts/production-mode.txt",
    "production-mode/receipts/production-lifecycle.txt": "receipts/production-lifecycle.txt",
    "production-mode/receipts/readiness-db-down.txt": "receipts/readiness-db-down.txt",
}
# Paths a later commit may change without making a run's receipts stale: prose and the receipts.
NOT_CODE = re.compile(r"^(receipts/.*|acceptance-report\.txt|[A-Z_-]+\.md)$")


def gh(*args: str) -> str:
    code, output = run(["gh", *args], merge=False, timeout=900)
    return must(code, output, "gh " + " ".join(args[:3]))


def cmd_fetch(args) -> None:
    head = must(*run(["git", "rev-parse", "HEAD"], merge=False), "git rev-parse").strip()
    fields = "databaseId,headSha,conclusion,status,createdAt,event,url,jobs"
    if args.run:
        info = json.loads(gh("run", "view", str(args.run), "--json", fields))
    else:
        runs = json.loads(gh("run", "list", "--workflow", "acceptance.yml", "--limit", "30", "--json", "databaseId,headSha,conclusion"))
        green = [row for row in runs if row["conclusion"] == "success"]
        if not green:
            raise Failed("no green acceptance run")
        info = json.loads(gh("run", "view", str(green[0]["databaseId"]), "--json", fields))
    if info["status"] != "completed" or info["conclusion"] != "success":
        raise Failed(f"run {info['databaseId']} is {info['status']}/{info['conclusion']}, not a green run")
    changed = must(*run(["git", "diff", "--name-only", info["headSha"], head], merge=False), "git diff").split()
    code_changes = [path for path in changed if not NOT_CODE.match(path)]
    if code_changes:
        raise Failed(f"run {info['databaseId']} tested {info['headSha'][:12]}; since then these changed: {code_changes[:10]}")
    with tempfile.TemporaryDirectory() as scratch:
        gh("run", "download", str(info["databaseId"]), "--dir", scratch)
        amd = (Path(scratch) / "acceptance-amd64" / "acceptance-report.txt").read_bytes()
        arm = (Path(scratch) / "acceptance-arm64" / "acceptance-report.txt").read_bytes()
        if amd != arm:
            raise Failed("the amd64 and arm64 acceptance reports differ")
        for source, target in FROM_CI.items():
            path = Path(scratch) / source
            if not path.exists():
                raise Failed(f"run {info['databaseId']} has no {source}")
            (ROOT / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, ROOT / target)
            print(f"copied {source} -> {target}")
    lines = [
        f"run {info['url']}",
        f"commit {info['headSha']}",
        f"event {info['event']}, created {info['createdAt']}, conclusion {info['conclusion']}",
    ]
    lines += [f"job {job['name']}: {job['conclusion']}" for job in info.get("jobs", [])]
    write(RECEIPTS / "ci-run.txt", "\n".join(lines) + "\n")
    cmd_inputs(args)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inputs")
    stack = sub.add_parser("stack")
    stack.add_argument("--base-url", default=None, help="default: base_url in .dogfood.toml")
    stack.add_argument("--tests", choices=["docker", "native", "skip"], default="docker")
    stack.add_argument("--oracle", choices=["docker", "native", "skip"], default="docker")
    backup = sub.add_parser("backup")
    backup.add_argument("--base-url", default=None)
    sub.add_parser("production")
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--run", type=int, default=None, help="default: the newest green acceptance run")
    args = parser.parse_args(argv[1:])
    handlers = {"inputs": cmd_inputs, "stack": cmd_stack, "backup": cmd_backup, "production": cmd_production, "fetch": cmd_fetch}
    try:
        handlers[args.command](args)
    except Failed as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
