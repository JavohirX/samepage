"""RFC 9162 style Merkle Tree and Ed25519 signing (S7).

Domain logic: pure Python and standard cryptography library. Free of Django.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def leaf_hash(data: bytes) -> bytes:
    """RFC 9162 Section 2.1: Leaf Hash = SHA-256(0x00 || data)."""
    return hashlib.sha256(b"\x00" + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    """RFC 9162 Section 2.1: Node Hash = SHA-256(0x01 || left || right)."""
    return hashlib.sha256(b"\x01" + left + right).digest()


def _largest_power_of_two_less_than(n: int) -> int:
    if n <= 1:
        return 0
    k = 1
    while (k << 1) < n:
        k <<= 1
    return k


def build_merkle_tree(leaf_hashes: list[bytes]) -> tuple[bytes, dict[str, Any]]:
    """Build an RFC 9162 Merkle tree from a list of leaf hashes.

    Returns (root_hash, tree_structure).
    """
    n = len(leaf_hashes)
    if n == 0:
        return hashlib.sha256(b"").digest(), {"n": 0}
    if n == 1:
        return leaf_hashes[0], {"n": 1, "hash": leaf_hashes[0]}

    k = _largest_power_of_two_less_than(n)
    left_root, left_tree = build_merkle_tree(leaf_hashes[:k])
    right_root, right_tree = build_merkle_tree(leaf_hashes[k:])
    root = node_hash(left_root, right_root)

    return root, {
        "n": n,
        "k": k,
        "hash": root,
        "left": left_tree,
        "right": right_tree,
    }


def compute_merkle_root(leaf_hashes: list[bytes]) -> bytes:
    """Compute the Merkle root hash for a list of leaf hashes."""
    root, _ = build_merkle_tree(leaf_hashes)
    return root


def generate_inclusion_proof(leaf_index: int, leaf_hashes: list[bytes]) -> list[dict[str, str]]:
    """Generate RFC 9162 inclusion proof for leaf at leaf_index (0-indexed).

    Returns list of dicts: [{"direction": "left" | "right", "hash": "<hex>"}]
    """
    n = len(leaf_hashes)
    if leaf_index < 0 or leaf_index >= n:
        raise ValueError(f"Leaf index {leaf_index} out of bounds for size {n}")

    def _proof(m: int, hashes: list[bytes]) -> list[dict[str, str]]:
        count = len(hashes)
        if count <= 1:
            return []
        k = _largest_power_of_two_less_than(count)
        if m < k:
            right_root = compute_merkle_root(hashes[k:])
            return _proof(m, hashes[:k]) + [{"direction": "right", "hash": right_root.hex()}]
        else:
            left_root = compute_merkle_root(hashes[:k])
            return _proof(m - k, hashes[k:]) + [{"direction": "left", "hash": left_root.hex()}]

    return _proof(leaf_index, leaf_hashes)


def verify_inclusion_proof(
    leaf_bytes: bytes,
    proof: list[dict[str, str]],
    expected_root_hex: str,
) -> bool:
    """Verify an RFC 9162 inclusion proof against the expected root hash."""
    current = leaf_hash(leaf_bytes)
    for step in proof:
        sibling = bytes.fromhex(step["hash"])
        if step["direction"] == "right":
            current = node_hash(current, sibling)
        elif step["direction"] == "left":
            current = node_hash(sibling, current)
        else:
            raise ValueError(f"Invalid direction: {step.get('direction')}")
    return current.hex() == expected_root_hex.lower()


# --- Ed25519 Signing ---

def generate_key_pair() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    priv = ed25519.Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def export_private_key_pem(priv: ed25519.Ed25519PrivateKey) -> bytes:
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def export_public_key_pem(pub: ed25519.Ed25519PublicKey) -> bytes:
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def load_private_key_pem(pem: bytes) -> ed25519.Ed25519PrivateKey:
    return serialization.load_pem_private_key(pem, password=None)


def load_public_key_pem(pem: bytes) -> ed25519.Ed25519PublicKey:
    return serialization.load_pem_public_key(pem)


def sign_data(priv: ed25519.Ed25519PrivateKey, data: bytes) -> bytes:
    """Sign raw bytes with Ed25519 private key."""
    return priv.sign(data)


def verify_signature(pub: ed25519.Ed25519PublicKey, signature: bytes, data: bytes) -> bool:
    """Verify raw bytes signature against Ed25519 public key."""
    try:
        pub.verify(signature, data)
        return True
    except InvalidSignature:
        return False
