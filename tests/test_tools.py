"""The receipt tools: what tools/verify.py accepts before it writes a receipt, and what
tools/lifecycle_check.py prints. Pure tests: gh, git, docker and HTTP are replaced by canned
answers, and every file is written under tmp_path, never into the checkout.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"samepage_tool_{name}", ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load("verify")
lifecycle = _load("lifecycle_check")

VERDICT = "claimed T1 T2, verified T1 T2"


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A stand-in checkout: verify.py's ROOT, receipts and .dogfood.toml all live in tmp_path."""
    (tmp_path / "run.py").write_bytes(b"print('checker')\n")
    (tmp_path / "fixtures.json").write_bytes(b'{"events": []}\n')
    (tmp_path / ".dogfood.toml").write_text((ROOT / ".dogfood.toml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify, "RECEIPTS", tmp_path / "receipts")
    monkeypatch.setattr(verify, "TOML", tmp_path / ".dogfood.toml")
    return tmp_path


# --- lifecycle_check prints one-time links without their secrets ----------------------------


@pytest.mark.parametrize(
    ("path", "printed"),
    [
        ("/join/tj_1AOIE4C3r7y484Loh0usvzntOMR0PewO.json", "/join/tj_1AO....json"),
        ("/password/pw_zaFcYHT1EuGMuF66cwxul_sSway0ZnBu", "/password/pw_zaF..."),
        ("/accept/ra_Q2w9x8LmNoPqRsTuVwXy.json", "/accept/ra_Q2w....json"),
    ],
)
def test_lifecycle_check_cuts_one_time_link_secrets(path, printed):
    assert lifecycle.shown(path) == printed
    secret = path.split("/")[2].removesuffix(".json")
    assert secret not in lifecycle.shown(path)


@pytest.mark.parametrize("path", ["/e/evt_01/projects.json", "/login", "/e/evt_01/teams/tm_01/invite.json", "/join/short"])
def test_lifecycle_check_prints_other_paths_as_they_are(path):
    assert lifecycle.shown(path) == path


# --- inputs and the checker verdict ---------------------------------------------------------


def test_inputs_writes_the_sha256_of_run_py_and_fixtures(checkout):
    verify.main(["verify.py", "inputs"])
    lines = (checkout / "receipts" / "inputs.txt").read_text(encoding="utf-8").splitlines()
    assert lines == [
        f"run.py {hashlib.sha256((checkout / 'run.py').read_bytes()).hexdigest()}",
        f"fixtures.json {hashlib.sha256((checkout / 'fixtures.json').read_bytes()).hexdigest()}",
    ]


@pytest.mark.parametrize(
    ("code", "report"),
    [
        (0, "PASS gallery\nclaimed T1 T2, verified T1\n"),
        (1, f"FAIL csv_export\n{VERDICT}\n"),
        (0, "PASS gallery\n"),
    ],
)
def test_the_checker_must_end_in_the_claimed_verdict(checkout, monkeypatch, code, report):
    monkeypatch.setattr(verify, "run", lambda args, **kw: (code, report))
    with pytest.raises(verify.Failed):
        verify.checker(Path(".dogfood.toml"))


def test_toml_for_points_a_copy_at_another_base(checkout, tmp_path):
    assert verify.toml_for("http://localhost:8080", tmp_path) == Path(".dogfood.toml")
    other = verify.toml_for("http://127.0.0.1:19100", tmp_path)
    text = other.read_text(encoding="utf-8")
    assert 'base_url = "http://127.0.0.1:19100"' in text
    assert "localhost:8080" not in text
    assert text.count("Authorization: Bearer") == 4


# --- stack: the tests receipt ---------------------------------------------------------------


def _stack_args(tests: str, oracle: str = "skip"):
    return ["verify.py", "stack", "--base-url", "http://localhost:8080", "--tests", tests, "--oracle", oracle]


def test_stack_writes_the_tests_receipt_and_fails_on_a_failed_test(checkout, monkeypatch):
    monkeypatch.setattr(verify, "http", lambda *a, **kw: (200, "text/plain", b"ok"))

    def run(args, **kw):
        if "pytest" in args:
            return 1, "..F.\n3 passed, 1 failed in 2.00s\n"
        return 0, f"PASS gallery\n{VERDICT}\n"

    monkeypatch.setattr(verify, "run", run)
    assert verify.main(_stack_args("native")) == 1
    assert "1 failed" in (checkout / "receipts" / "tests.txt").read_text(encoding="utf-8")


def test_stack_passes_when_both_reports_match_and_the_tests_pass(checkout, monkeypatch):
    monkeypatch.setattr(verify, "http", lambda *a, **kw: (200, "text/plain", b"ok"))
    monkeypatch.setattr(
        verify, "run", lambda args, **kw: (0, "....\n4 passed in 2.00s\n") if "pytest" in args else (0, f"PASS\n{VERDICT}\n")
    )
    assert verify.main(_stack_args("native")) == 0
    assert (checkout / "acceptance-report.txt").read_text(encoding="utf-8") == f"PASS\n{VERDICT}\n"


def test_stack_fails_when_the_second_report_differs(checkout, monkeypatch):
    monkeypatch.setattr(verify, "http", lambda *a, **kw: (200, "text/plain", b"ok"))
    reports = iter([f"PASS 7/7 in 1.0 s\n{VERDICT}\n", f"PASS 7/7 in 1.1 s\n{VERDICT}\n"])
    monkeypatch.setattr(verify, "run", lambda args, **kw: (0, next(reports)))
    assert verify.main(_stack_args("skip")) == 1


# --- backup: the restore must bring back the backed-up ledger --------------------------------


class Portal:
    """The three reads and the one write cmd_backup makes, over a state a dump can copy."""

    def __init__(self):
        self.state = {"csv": b"judge,project,score\njdg_01,prj_07,5\n", "audit": 128, "dup": ("provisional", "keep_latest")}
        self.dump = None

    def http(self, method, url, *, headers=None, body=None, timeout=30):
        if method == "POST" and url.endswith("/duplicates/dup_01/confirm.json"):
            self.state["csv"] += b"merged\n"
            self.state["audit"] += 1
            self.state["dup"] = ("confirmed", body["resolution"])
            return 200, "application/json", b"{}"
        if url.endswith("/healthz"):
            return 200, "text/plain", b"ok"
        if url.endswith("/scores.csv"):
            return 200, "text/csv", self.state["csv"]
        if url.endswith("/audit.json"):
            return 200, "application/json", json.dumps({"count": self.state["audit"], "chain_ok": "true"}).encode()
        if url.endswith("/duplicates/dup_01.json"):
            status, resolution = self.state["dup"]
            return 200, "application/json", json.dumps({"status": status, "resolution": resolution}).encode()
        return 404, "application/problem+json", b"{}"


def _backup(checkout, monkeypatch, *, restore_works: bool) -> int:
    portal = Portal()

    def run(args, **kw):
        if args[-1] == "backup":
            portal.dump = copy.deepcopy(portal.state)
        elif args[-1] == "restore" and restore_works:
            portal.state = copy.deepcopy(portal.dump)
        elif "run.py" in args:
            return 0, f"PASS\n{VERDICT}\n"
        return 0, ""

    monkeypatch.setattr(verify, "http", portal.http)
    monkeypatch.setattr(verify, "run", run)
    return verify.main(["verify.py", "backup", "--base-url", "http://localhost:8080"])


def test_backup_receipt_says_the_restore_undid_the_change(checkout, monkeypatch):
    assert _backup(checkout, monkeypatch, restore_works=True) == 0
    receipt = (checkout / "receipts" / "backup-restore.txt").read_text(encoding="utf-8")
    assert "dup_01 confirmed merge" in receipt
    assert receipt.count("dup_01 provisional keep_latest") == 2
    assert "PASS: the restore brought back" in receipt
    assert receipt.rstrip().endswith(VERDICT)


def test_backup_fails_and_writes_no_receipt_when_the_restore_changes_nothing(checkout, monkeypatch):
    assert _backup(checkout, monkeypatch, restore_works=False) == 1
    assert not (checkout / "receipts" / "backup-restore.txt").exists()


# --- fetch: only a green run of this code ---------------------------------------------------

HEAD = "a" * 40
TESTED = "b" * 40


def _fetch(checkout, monkeypatch, *, conclusion="success", changed=("README.md", "receipts/ci-run.txt"), arm_report=None):
    report = f"PASS\n{VERDICT}\n"

    def run(args, **kw):
        if args[:2] == ["git", "rev-parse"]:
            return 0, HEAD + "\n"
        if args[:2] == ["git", "diff"]:
            assert args[-2:] == [TESTED, HEAD]
            return 0, "\n".join(changed) + "\n"
        if args[:3] == ["gh", "run", "list"]:
            return 0, json.dumps([{"databaseId": 7, "headSha": TESTED, "conclusion": conclusion}])
        if args[:3] == ["gh", "run", "view"]:
            info = {
                "databaseId": int(args[3]), "headSha": TESTED, "conclusion": conclusion, "status": "completed",
                "createdAt": "2026-09-29T00:00:00Z", "event": "push", "url": "https://github.com/o/r/actions/runs/7",
                "jobs": [{"name": "docker compose (amd64)", "conclusion": conclusion}],
            }
            return 0, json.dumps(info)
        if args[:3] == ["gh", "run", "download"]:
            scratch = Path(args[args.index("--dir") + 1])
            for source in verify.FROM_CI:
                (scratch / source).parent.mkdir(parents=True, exist_ok=True)
                (scratch / source).write_text(f"from CI: {source}\n", encoding="utf-8")
            (scratch / "acceptance-amd64" / "acceptance-report.txt").write_text(report, encoding="utf-8")
            (scratch / "acceptance-arm64").mkdir(parents=True, exist_ok=True)
            (scratch / "acceptance-arm64" / "acceptance-report.txt").write_text(arm_report or report, encoding="utf-8")
            return 0, ""
        raise AssertionError(f"unexpected command {args}")

    monkeypatch.setattr(verify, "run", run)
    return verify.main(["verify.py", "fetch", "--run", "7"])


def test_fetch_copies_every_receipt_from_a_green_run_of_this_code(checkout, monkeypatch):
    assert _fetch(checkout, monkeypatch) == 0
    assert (checkout / "acceptance-report.txt").read_text(encoding="utf-8") == f"PASS\n{VERDICT}\n"
    for source, target in verify.FROM_CI.items():
        if target != "acceptance-report.txt":
            assert (checkout / target).read_text(encoding="utf-8") == f"from CI: {source}\n"
    ci_run = (checkout / "receipts" / "ci-run.txt").read_text(encoding="utf-8")
    assert f"commit {TESTED}" in ci_run
    assert "job docker compose (amd64): success" in ci_run
    assert (checkout / "receipts" / "inputs.txt").exists()


def test_fetch_refuses_a_run_that_is_not_green(checkout, monkeypatch):
    assert _fetch(checkout, monkeypatch, conclusion="failure") == 1
    assert not (checkout / "receipts" / "ci-run.txt").exists()


def test_fetch_refuses_a_run_that_tested_other_code(checkout, monkeypatch):
    assert _fetch(checkout, monkeypatch, changed=("README.md", "samepage/services/judging.py")) == 1
    assert not (checkout / "receipts").exists()


def test_fetch_refuses_runs_whose_amd64_and_arm64_reports_differ(checkout, monkeypatch):
    assert _fetch(checkout, monkeypatch, arm_report="PASS\nclaimed T1 T2, verified T1\n") == 1
    assert not (checkout / "acceptance-report.txt").exists()


@pytest.mark.parametrize(
    ("path", "is_code"),
    [
        ("README.md", False),
        ("OPERATIONS.md", False),
        ("receipts/tests.txt", False),
        ("acceptance-report.txt", False),
        ("tools/verify.py", True),
        (".github/workflows/acceptance.yml", True),
        ("docs/notes.md", True),
        ("docker-compose.yml", True),
    ],
)
def test_only_receipts_and_top_level_prose_may_change_after_the_tested_commit(path, is_code):
    assert (verify.NOT_CODE.match(path) is None) is is_code
