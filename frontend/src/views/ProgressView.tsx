import React, { useState, useEffect } from 'react';
import {
  Activity,
  CheckCircle2,
  FileSpreadsheet,
  Hash,
  Check,
  ArrowRight,
  ShieldCheck,
} from 'lucide-react';
import type { ProgressPayload, AuditItem } from '../lib/types';
import type { TabType } from '../components/Header';
import { getProgress, getAuditEvents, getScoresCsvUrl } from '../lib/api';
import { FALLBACK_PROGRESS, FALLBACK_AUDIT } from '../lib/mockFallback';

interface ProgressViewProps {
  token?: string;
  onNavigateTab?: (tab: TabType) => void;
}

export const ProgressView: React.FC<ProgressViewProps> = ({ token, onNavigateTab }) => {
  const [progress, setProgress] = useState<ProgressPayload | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);
  const isOrganizer = !!token;

  useEffect(() => {

    Promise.allSettled([
      getProgress('evt_01', token),
      getAuditEvents('evt_01', token),
    ]).then(([progRes, auditRes]) => {
      if (progRes.status === 'fulfilled' && progRes.value) {
        setProgress(progRes.value);
      } else {
        setProgress(FALLBACK_PROGRESS);
      }

      if (auditRes.status === 'fulfilled' && auditRes.value?.items) {
        setAuditLogs(auditRes.value.items);
      } else {
        setAuditLogs(FALLBACK_AUDIT);
      }

      setLoading(false);
    });
  }, [token]);

  const copyHash = async (hash: string, id: string) => {
    try {
      await navigator.clipboard.writeText(hash);
      setCopiedHash(id);
      setTimeout(() => setCopiedHash(null), 2000);
    } catch {
      // fallback
    }
  };

  if (loading) {
    return (
      <div className="empty-state">
        <div className="spinner" />
        <p style={{ marginTop: '1rem', color: 'var(--text-secondary)' }}>Loading evaluation progress & audit logs...</p>
      </div>
    );
  }

  const s = progress?.sentence || FALLBACK_PROGRESS.sentence;
  const pctReviewed = s.active > 0 ? Math.round((s.fully_reviewed / s.active) * 100) : 0;
  const readyForReml = s.short === 0 && s.fully_reviewed >= s.active;

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: '2rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.35rem' }}>
              <h1 style={{ fontSize: '1.75rem', fontWeight: 600, letterSpacing: '-0.02em', margin: 0 }}>
                Organizer Operations & Audit
              </h1>
              {isOrganizer && (
                <span className="badge badge-success" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                  <ShieldCheck size={12} /> Authorized Organizer
                </span>
              )}
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', maxWidth: '640px' }}>
              Real-time submission quorum monitoring, consensus readiness, and cryptographic append-only audit trail.
            </p>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <a
              href={getScoresCsvUrl('evt_01')}
              target="_blank"
              rel="noreferrer"
              className="btn btn-secondary btn-sm"
              title="Download consensus scoring CSV dataset"
            >
              <FileSpreadsheet size={14} />
              <span>Export Raw CSV</span>
            </a>

            {onNavigateTab && (
              <button
                onClick={() => onNavigateTab('results')}
                className="btn btn-primary btn-sm"
              >
                <span>View REML Normalization</span>
                <ArrowRight size={14} />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Readiness Banner */}
      <div
        style={{
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          padding: '1.25rem 1.5rem',
          backgroundColor: readyForReml ? 'var(--bg-panel)' : 'var(--bg-panel)',
          borderLeft: `4px solid ${readyForReml ? 'var(--success)' : 'var(--accent)'}`,
          marginBottom: '2rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
            {readyForReml ? (
              <CheckCircle2 size={18} color="var(--success)" />
            ) : (
              <Activity size={18} color="var(--accent)" />
            )}
            <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>
              {readyForReml ? 'Ready for REML Normalization & Ranking' : 'Evaluation in Progress'}
            </span>
          </div>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0 }}>
            {s.fully_reviewed} of {s.active} projects have reached minimum review quota ({pctReviewed}% complete).{' '}
            {s.short > 0 ? `${s.short} project(s) still require top-up evaluation.` : 'All quotas satisfied.'}
          </p>
        </div>

        <div style={{ minWidth: '220px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
            <span>Review Quorum</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{pctReviewed}%</span>
          </div>
          <div style={{ height: 6, backgroundColor: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
            <div
              style={{
                width: `${pctReviewed}%`,
                height: '100%',
                backgroundColor: readyForReml ? 'var(--success)' : 'var(--accent)',
                transition: 'width 0.4s ease',
              }}
            />
          </div>
        </div>
      </div>

      {/* Key Metric Stat Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '1rem',
          marginBottom: '2.5rem',
        }}
      >
        <div className="card" style={{ padding: '1.25rem' }}>
          <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>
            Counted Reviews
          </div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            {s.counted}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            In consensus scoring matrix
          </div>
        </div>

        <div className="card" style={{ padding: '1.25rem' }}>
          <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>
            Excluded Reviews
          </div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: s.excluded > 0 ? 'var(--warning)' : 'inherit' }}>
            {s.excluded}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Conflict of interest or duplicates
          </div>
        </div>

        <div className="card" style={{ padding: '1.25rem' }}>
          <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>
            Active Projects
          </div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            {s.active}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Accepted submissions evaluated
          </div>
        </div>

        <div className="card" style={{ padding: '1.25rem' }}>
          <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>
            Pending Reviews
          </div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: s.short > 0 ? 'var(--accent)' : 'var(--success)' }}>
            {s.short}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Submissions needing top-up reviews
          </div>
        </div>
      </div>

      {/* Cryptographic Audit Trail */}
      <div style={{ marginBottom: '3rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <div>
            <h2 style={{ fontSize: '1.15rem', fontWeight: 600, letterSpacing: '-0.01em', marginBottom: '0.2rem' }}>
              Cryptographic Audit Log
            </h2>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              Hash-chained record of all scoring, convergence checks, and publication actions.
            </p>
          </div>

          <span
            style={{
              fontSize: '0.7rem',
              fontFamily: 'var(--font-mono)',
              padding: '0.2rem 0.5rem',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--bg-subtle)',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
            }}
          >
            SHA-256 HASH CHAIN
          </span>
        </div>

        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: '60px' }}>Seq</th>
                <th style={{ width: '140px' }}>Timestamp</th>
                <th style={{ width: '130px' }}>Actor</th>
                <th style={{ width: '140px' }}>Action</th>
                <th>Target / Details</th>
                <th style={{ width: '160px' }}>Entry Hash</th>
              </tr>
            </thead>
            <tbody>
              {auditLogs.map((log) => {
                const isCopied = copiedHash === `entry_${log.seq}`;
                return (
                  <tr key={log.seq}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>
                      #{log.seq}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      {new Date(log.timestamp).toLocaleString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </td>
                    <td>
                      <span
                        style={{
                          fontSize: '0.7rem',
                          fontFamily: 'var(--font-mono)',
                          padding: '0.15rem 0.4rem',
                          borderRadius: 'var(--radius-sm)',
                          backgroundColor:
                            log.role === 'organizer'
                              ? 'rgba(16, 185, 129, 0.1)'
                              : log.role === 'judge'
                              ? 'rgba(59, 130, 246, 0.1)'
                              : 'var(--bg-subtle)',
                          color:
                            log.role === 'organizer'
                              ? 'var(--success)'
                              : log.role === 'judge'
                              ? '#3b82f6'
                              : 'var(--text-secondary)',
                          border: '1px solid var(--border)',
                        }}
                      >
                        {log.role}
                      </span>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', fontWeight: 600 }}>
                      {log.action}
                    </td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      {log.target}
                    </td>
                    <td>
                      <button
                        onClick={() => copyHash(log.entry_hash, `entry_${log.seq}`)}
                        className="btn btn-secondary btn-sm"
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '0.7rem',
                          padding: '0.2rem 0.5rem',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.3rem',
                        }}
                        title={`Copy full hash: ${log.entry_hash}`}
                      >
                        {isCopied ? <Check size={11} color="var(--success)" /> : <Hash size={11} />}
                        <span>{log.entry_hash.slice(0, 10)}…</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
