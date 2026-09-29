"""Tests for RFC 9162 Merkle tree, Ed25519 signing, and OpenSSL verification (S7)."""

import base64
import hashlib
import os
import shutil
import subprocess
import pytest
from rest_framework.exceptions import PermissionDenied

from samepage.apps.portal.models import Event, JudgeProtocol, Person, ResultsSnapshot, SignedRoot
from samepage.domain import merkle
from samepage.services import results, signing

from conftest import needs_db

pytestmark = [needs_db, pytest.mark.django_db]


def test_rfc9162_merkle_tree_math():
    """Verify RFC 9162 Merkle tree construction and inclusion proof verification."""
    data_leaves = [f"REVIEW_DATA_{i}".encode("utf-8") for i in range(7)]
    leaf_hashes = [merkle.leaf_hash(d) for d in data_leaves]

    root, tree = merkle.build_merkle_tree(leaf_hashes)
    assert len(root) == 32

    # Verify inclusion proof for each leaf
    for i in range(len(data_leaves)):
        proof = merkle.generate_inclusion_proof(i, leaf_hashes)
        assert len(proof) > 0
        assert merkle.verify_inclusion_proof(data_leaves[i], proof, root.hex()) is True

    # Tampered leaf MUST fail inclusion proof
    tampered = b"TAMPERED_REVIEW_DATA"
    proof_0 = merkle.generate_inclusion_proof(0, leaf_hashes)
    assert merkle.verify_inclusion_proof(tampered, proof_0, root.hex()) is False


def test_ed25519_key_and_signing():
    """Verify Ed25519 key generation, PEM export/load, signing, and verification."""
    priv, pub = merkle.generate_key_pair()
    msg = b"SAMEPAGE_STATEMENT_TEST"
    sig = merkle.sign_data(priv, msg)

    assert merkle.verify_signature(pub, sig, msg) is True
    assert merkle.verify_signature(pub, sig, b"WRONG_MESSAGE") is False

    # PEM round-trip
    priv_pem = merkle.export_private_key_pem(priv)
    pub_pem = merkle.export_public_key_pem(pub)
    loaded_priv = merkle.load_private_key_pem(priv_pem)
    loaded_pub = merkle.load_public_key_pem(pub_pem)

    sig2 = merkle.sign_data(loaded_priv, msg)
    assert merkle.verify_signature(loaded_pub, sig2, msg) is True


def test_signed_records_publish_and_openssl_verification(client, tmp_path):
    """Publish results for evt_01, verify signed root and OpenSSL verify command."""
    event = Event.objects.get(id="evt_01")
    # Generate signed records
    signed_root = signing.generate_signed_records(event)
    assert signed_root.leaf_count > 0
    assert len(signed_root.root_hash) == 64
    assert signed_root.signature_ed25519

    # Verify via HTTP endpoints
    resp = client.get("/e/evt_01/records/root.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["root_hash"] == signed_root.root_hash

    resp_txt = client.get("/e/evt_01/records/root.txt")
    assert resp_txt.status_code == 200
    statement_bytes = resp_txt.content

    resp_sig = client.get("/e/evt_01/records/root.sig")
    assert resp_sig.status_code == 200
    sig_bytes = resp_sig.content

    resp_pem = client.get("/e/evt_01/records/pub.pem")
    assert resp_pem.status_code == 200
    pem_bytes = resp_pem.content

    # If openssl binary exists on host, run real openssl command
    openssl_bin = shutil.which("openssl")
    if openssl_bin:
        txt_path = tmp_path / "root.txt"
        sig_path = tmp_path / "root.sig"
        pem_path = tmp_path / "pub.pem"

        txt_path.write_bytes(statement_bytes)
        sig_path.write_bytes(sig_bytes)
        pem_path.write_bytes(pem_bytes)

        cmd = [
            openssl_bin,
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            str(pem_path),
            "-rawin",
            "-in",
            str(txt_path),
            "-sigfile",
            str(sig_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0, f"OpenSSL verify failed: {proc.stderr}"
        assert "Signature Verified Successfully" in proc.stdout or proc.returncode == 0

        # Tampered statement must fail OpenSSL verification
        txt_path.write_bytes(b"TAMPERED STATEMENT")
        proc_bad = subprocess.run(cmd, capture_output=True, text=True)
        assert proc_bad.returncode != 0


def test_judge_protocol_authorization(client, bearer):
    """Judge protocol is readable only by that judge and organizers; 403 to other judges."""
    event = Event.objects.get(id="evt_01")
    signing.generate_signed_records(event)

    # jdg_08 accesses their own protocol
    resp_08 = client.get("/e/evt_01/judge/protocol.json", **bearer("jdg08"))
    assert resp_08.status_code == 200
    data_08 = resp_08.json()
    assert data_08["judge_id"] == "jdg_08"
    assert len(data_08["reviews"]) > 0
    assert "inclusion_proof" in data_08["reviews"][0]

    # jdg_03 accesses their own protocol
    resp_03 = client.get("/e/evt_01/judge/protocol.json", **bearer("jdg03"))
    assert resp_03.status_code == 200
    assert resp_03.json()["judge_id"] == "jdg_03"

    # jdg_03 attempts IDOR by requesting jdg_08's protocol -> 403
    resp_idor = client.get("/e/evt_01/judge/protocol.json?judge=jdg_08", **bearer("jdg03"))
    assert resp_idor.status_code == 403

    # Organizer can view jdg_08's protocol
    resp_org = client.get("/e/evt_01/judge/protocol.json?judge=jdg_08", **bearer("org"))
    assert resp_org.status_code == 200
    assert resp_org.json()["judge_id"] == "jdg_08"
