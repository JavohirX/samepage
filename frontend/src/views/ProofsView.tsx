import React, { useState, useEffect } from 'react';
import { ShieldCheck, Hash, FileKey, Copy, Check, ExternalLink } from 'lucide-react';
import type { SignedRootPayload } from '../lib/types';
import { getSignedRoot, getCertificateUrl } from '../lib/api';
import { FALLBACK_SIGNED_ROOT } from '../lib/mockFallback';

export const ProofsView: React.FC = () => {
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
    return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-tertiary)' }}>Loading cryptographic records...</div>;
  }

  if (!root) return null;

  return (
    <div>
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, letterSpacing: '-0.03em', marginBottom: '0.35rem' }}>
          Cryptographic Integrity Proofs
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          RFC 9162 Merkle tree with Ed25519-signed root hash. Every score, review, and state transition is a leaf — independently verifiable.
        </p>
      </div>

      {/* Root Hash & Signature Section */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
        <div className="card" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.75rem' }}>
            <Hash size={16} color="var(--accent)" />
            <h3 style={{ fontSize: '0.85rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
              Merkle Root Hash
            </h3>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <code className="code-block" style={{ flex: 1, fontSize: '0.7rem', wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>
              {root.root_hash}
            </code>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => copyToClipboard(root.root_hash, 'hash')}
              style={{ flexShrink: 0 }}
            >
              {copied === 'hash' ? <Check size={13} /> : <Copy size={13} />}
            </button>
          </div>
        </div>

        <div className="card" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.75rem' }}>
            <FileKey size={16} color="var(--accent)" />
            <h3 style={{ fontSize: '0.85rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
              Ed25519 Signature
            </h3>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <code className="code-block" style={{ flex: 1, fontSize: '0.7rem', wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>
              {root.signature_ed25519}
            </code>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => copyToClipboard(root.signature_ed25519, 'sig')}
              style={{ flexShrink: 0 }}
            >
              {copied === 'sig' ? <Check size={13} /> : <Copy size={13} />}
            </button>
          </div>
        </div>
      </div>

      {/* Metadata */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '0.75rem', marginBottom: '1.5rem' }}>
        <div className="card" style={{ padding: '1rem' }}>
          <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Leaf Count</p>
          <p style={{ fontSize: '1.25rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{root.leaf_count}</p>
        </div>
        <div className="card" style={{ padding: '1rem' }}>
          <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Publish Seq</p>
          <p style={{ fontSize: '1.25rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{root.publish_seq}</p>
        </div>
        <div className="card" style={{ padding: '1rem' }}>
          <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Algorithm</p>
          <p style={{ fontSize: '1rem', fontWeight: 600 }}>Ed25519</p>
        </div>
        <div className="card" style={{ padding: '1rem' }}>
          <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Standard</p>
          <p style={{ fontSize: '1rem', fontWeight: 600 }}>RFC 9162</p>
        </div>
      </div>

      {/* Signed Statement */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.75rem' }}>
          <ShieldCheck size={16} color="var(--accent)" />
          <h3 style={{ fontSize: '0.85rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
            Signed Statement
          </h3>
        </div>
        <pre className="code-block" style={{ whiteSpace: 'pre-wrap', fontSize: '0.75rem', lineHeight: 1.6 }}>
          {root.statement}
        </pre>
      </div>

      {/* Public Key */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
          <h3 style={{ fontSize: '0.85rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
            Public Verification Key
          </h3>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => copyToClipboard(root.public_key_pem, 'pem')}
          >
            {copied === 'pem' ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy PEM</>}
          </button>
        </div>
        <pre className="code-block" style={{ fontSize: '0.7rem' }}>
          {root.public_key_pem}
        </pre>
      </div>

      {/* Verify Command */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <h3 style={{ fontSize: '0.85rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)', marginBottom: '0.75rem' }}>
          Independent Verification Command
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <code className="code-block" style={{ flex: 1, fontSize: '0.75rem' }}>
            {root.verify_command}
          </code>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => copyToClipboard(root.verify_command, 'cmd')}
            style={{ flexShrink: 0 }}
          >
            {copied === 'cmd' ? <Check size={12} /> : <Copy size={12} />}
          </button>
        </div>
      </div>

      {/* Direct Download Links */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <a href={`/api/backend/e/evt_01/records/root.txt`} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
          root.txt <ExternalLink size={11} />
        </a>
        <a href={`/api/backend/e/evt_01/records/root.sig`} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
          root.sig <ExternalLink size={11} />
        </a>
        <a href={`/api/backend/e/evt_01/records/pub.pem`} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
          pub.pem <ExternalLink size={11} />
        </a>
        <a href={getCertificateUrl('tm_01')} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
          Sample Certificate (SVG) <ExternalLink size={11} />
        </a>
      </div>
    </div>
  );
};
