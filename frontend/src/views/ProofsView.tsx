import React, { useState, useEffect } from 'react';
import { ShieldCheck, Hash, FileKey, Copy, Check, X } from 'lucide-react';
import type { SignedRootPayload } from '../lib/types';
import { getSignedRoot } from '../lib/api';
import { FALLBACK_SIGNED_ROOT } from '../lib/mockFallback';

interface ProofsViewProps {
  onClose?: () => void;
  isModal?: boolean;
}

export const ProofsView: React.FC<ProofsViewProps> = ({ onClose, isModal = false }) => {
  const [root, setRoot] = useState<SignedRootPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    getSignedRoot()
      .then((data) => {
        setRoot(data);
        setLoading(false);
      })
      .catch(() => {
        setRoot(FALLBACK_SIGNED_ROOT);
        setLoading(false);
      });
  }, []);

  const copyToClipboard = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      // fallback
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-tertiary)' }}>
        Loading cryptographic records...
      </div>
    );
  }

  if (!root) return null;

  const content = (
    <div style={{ position: 'relative' }}>
      <div style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
            <ShieldCheck size={20} color="var(--success)" />
            <h2 style={{ fontSize: '1.35rem', fontWeight: 600, letterSpacing: '-0.02em', margin: 0 }}>
              Cryptographic Integrity Proofs
            </h2>
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
            RFC 9162 Merkle tree with Ed25519-signed root hash. Every evaluation is an immutable leaf.
          </p>
        </div>

        {isModal && onClose && (
          <button
            onClick={onClose}
            className="theme-toggle-btn"
            style={{ border: 'none', background: 'transparent' }}
            title="Close"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {/* Root Hash & Signature Section */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem', marginBottom: '1.25rem' }}>
        <div className="card" style={{ padding: '1.15rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.5rem' }}>
            <Hash size={15} color="var(--accent)" />
            <span style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
              Merkle Root Hash (SHA-256)
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <code className="font-mono" style={{ fontSize: '0.78rem', wordBreak: 'break-all', flex: 1, color: 'var(--text-primary)' }}>
              {root.root_hash}
            </code>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => copyToClipboard(root.root_hash, 'root_hash')}
              title="Copy root hash"
            >
              {copied === 'root_hash' ? <Check size={12} color="var(--success)" /> : <Copy size={12} />}
            </button>
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '0.4rem' }}>
            Commitment over {root.leaf_count} immutable evaluation leaves
          </div>
        </div>

        <div className="card" style={{ padding: '1.15rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.5rem' }}>
            <FileKey size={15} color="var(--accent)" />
            <span style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
              Ed25519 Root Signature
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <code className="font-mono" style={{ fontSize: '0.78rem', wordBreak: 'break-all', flex: 1, color: 'var(--text-primary)' }}>
              {root.signature_ed25519.slice(0, 32)}…
            </code>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => copyToClipboard(root.signature_ed25519, 'signature')}
              title="Copy base64 Ed25519 signature"
            >
              {copied === 'signature' ? <Check size={12} color="var(--success)" /> : <Copy size={12} />}
            </button>
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '0.4rem' }}>
            Sequence #{root.publish_seq} signed with organizer private key
          </div>
        </div>
      </div>

      {/* Terminal Verification Command */}
      <div className="card" style={{ padding: '1.15rem', marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <span style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
            Independent OpenSSL Verification
          </span>
          <button
            className="btn btn-secondary btn-sm"
            style={{ fontSize: '0.72rem' }}
            onClick={() => copyToClipboard(root.verify_command, 'cmd')}
          >
            {copied === 'cmd' ? <Check size={12} color="var(--success)" /> : <Copy size={12} />}
            <span>Copy Command</span>
          </button>
        </div>
        <div className="code-block" style={{ fontSize: '0.78rem', padding: '0.65rem 0.85rem' }}>
          {root.verify_command}
        </div>
      </div>

      {/* Public Key PEM */}
      <div className="card" style={{ padding: '1.15rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <span style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
            Event Authority Public Key (Ed25519 PEM)
          </span>
          <button
            className="btn btn-secondary btn-sm"
            style={{ fontSize: '0.72rem' }}
            onClick={() => copyToClipboard(root.public_key_pem, 'pem')}
          >
            {copied === 'pem' ? <Check size={12} color="var(--success)" /> : <Copy size={12} />}
            <span>Copy PEM</span>
          </button>
        </div>
        <div className="code-block" style={{ fontSize: '0.75rem', whiteSpace: 'pre-wrap', maxHeight: '110px', overflowY: 'auto' }}>
          {root.public_key_pem}
        </div>
      </div>
    </div>
  );

  if (isModal) {
    return (
      <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
        <div className="modal-dialog" style={{ maxWidth: '780px' }} onClick={(e) => e.stopPropagation()}>
          {content}
        </div>
      </div>
    );
  }

  return content;
};
