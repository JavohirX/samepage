import React, { useState, useEffect } from 'react';
import { ClipboardCheck, Save, Lock, ExternalLink, GitBranch, AlertCircle } from 'lucide-react';
import type { JudgeBatchItem, AssignmentSheet, Criterion } from '../lib/types';
import { getJudgeBatches, getJudgeAssignment, saveJudgeScores, finalizeJudgeAssignment } from '../lib/api';
import { FALLBACK_BATCHES, FALLBACK_ASSIGNMENT } from '../lib/mockFallback';

interface JudgeViewProps {
  token?: string;
}

export const JudgeView: React.FC<JudgeViewProps> = ({ token }) => {
  const [batches, setBatches] = useState<JudgeBatchItem[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [assignment, setAssignment] = useState<AssignmentSheet | null>(null);
  const [scores, setScores] = useState<Record<string, number>>({});
  const [comment, setComment] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [noAuth, setNoAuth] = useState(false);

  useEffect(() => {
    if (!token) {
      setNoAuth(true);
      setBatches(FALLBACK_BATCHES);
      setLoading(false);
      return;
    }
    setNoAuth(false);
    getJudgeBatches('evt_01', token)
      .then((data) => {
        setBatches(data.items || []);
        setLoading(false);
      })
      .catch(() => {
        setBatches(FALLBACK_BATCHES);
        setLoading(false);
      });
  }, [token]);

  const loadAssignment = (projectId: string) => {
    setSelectedProject(projectId);
    setAssignment(null);
    setSaveMsg('');

    if (!token) {
      const fallback = { ...FALLBACK_ASSIGNMENT, project_id: projectId, title: batches.find((b) => b.project_id === projectId)?.title || projectId };
      setAssignment(fallback);
      const initialScores: Record<string, number> = {};
      fallback.criteria.forEach((c) => {
        initialScores[c.key] = Number(c.value) || 0;
      });
      setScores(initialScores);
      setComment(fallback.comment || '');
      return;
    }

    getJudgeAssignment(projectId, 'evt_01', token)
      .then((data) => {
        setAssignment(data);
        const initialScores: Record<string, number> = {};
        data.criteria.forEach((c: Criterion) => {
          initialScores[c.key] = Number(c.value) || 0;
        });
        setScores(initialScores);
        setComment(data.comment || '');
      })
      .catch(() => {
        const fallback = { ...FALLBACK_ASSIGNMENT, project_id: projectId };
        setAssignment(fallback);
        const initialScores: Record<string, number> = {};
        fallback.criteria.forEach((c) => {
          initialScores[c.key] = Number(c.value) || 0;
        });
        setScores(initialScores);
        setComment(fallback.comment || '');
      });
  };

  const handleSave = async () => {
    if (!token || !selectedProject) return;
    setSaving(true);
    try {
      await saveJudgeScores(selectedProject, scores, comment, token);
      setSaveMsg('Draft scores saved successfully.');
    } catch (err: any) {
      setSaveMsg(`Save failed: ${err.message}`);
    }
    setSaving(false);
  };

  const handleFinalize = async () => {
    if (!token || !selectedProject) return;
    if (!confirm('Finalize this review? Scores will be locked into the audit chain and cannot be changed.')) return;
    setSaving(true);
    try {
      await finalizeJudgeAssignment(selectedProject, token);
      setSaveMsg('Review finalized and locked into audit chain.');
      if (assignment) {
        setAssignment({ ...assignment, finalized: true });
      }
    } catch (err: any) {
      setSaveMsg(`Finalize failed: ${err.message}`);
    }
    setSaving(false);
  };

  return (
    <div>
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, letterSpacing: '-0.03em', marginBottom: '0.35rem' }}>
          Judge Scoring Console
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Weighted rubric scoring with autosave, keyboard navigation, and append-only audit finalization.
        </p>
        {noAuth && (
          <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--warning)', fontSize: '0.8125rem' }}>
            <AlertCircle size={14} />
            <span>Switch to a <strong>Judge</strong> persona above to access live scoring with the backend.</span>
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '1.5rem', alignItems: 'flex-start' }}>
        {/* Batch Assignment List */}
        <div className="card" style={{ padding: '0' }}>
          <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-subtle)' }}>
            <h3 style={{ fontSize: '0.85rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
              Your Assigned Batch
            </h3>
          </div>
          {loading ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
              Loading assignments...
            </div>
          ) : batches.length === 0 ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
              No assignments found for this judge persona.
            </div>
          ) : (
            <div>
              {batches.map((batch) => (
                <button
                  key={batch.project_id}
                  onClick={() => loadAssignment(batch.project_id)}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    padding: '0.85rem 1.25rem',
                    border: 'none',
                    borderBottom: '1px solid var(--border-subtle)',
                    backgroundColor: selectedProject === batch.project_id ? 'var(--accent-subtle)' : 'transparent',
                    cursor: 'pointer',
                    transition: 'background 100ms',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <div>
                    <p style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.15rem' }}>
                      {batch.title}
                    </p>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                      {batch.project_id} · {batch.track}
                    </p>
                  </div>
                  <span
                    className={`badge ${batch.finalized === true || batch.finalized === 'true' ? 'badge-success' : 'badge-accent'}`}
                    style={{ fontSize: '0.7rem' }}
                  >
                    {batch.finalized === true || batch.finalized === 'true' ? 'Finalized' : batch.status}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Scoring Sheet */}
        <div className="card">
          {!assignment ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-tertiary)' }}>
              <ClipboardCheck size={28} style={{ marginBottom: '0.75rem', opacity: 0.4 }} />
              <p style={{ fontSize: '0.9rem' }}>Select a project from your batch to begin scoring.</p>
            </div>
          ) : (
            <div>
              <div style={{ marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                  <span className="badge badge-accent">{assignment.track}</span>
                  <span className="badge font-mono">{assignment.project_id}</span>
                  {assignment.finalized && <span className="badge badge-success"><Lock size={10} /> Finalized</span>}
                </div>
                <h2 style={{ fontSize: '1.3rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
                  {assignment.title}
                </h2>
                {assignment.tagline && (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '0.25rem' }}>
                    {assignment.tagline}
                  </p>
                )}

                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
                  {assignment.repo_url && (
                    <a href={assignment.repo_url} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
                      <GitBranch size={13} /> Source
                      <ExternalLink size={11} />
                    </a>
                  )}
                  {assignment.live_url && (
                    <a href={assignment.live_url} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
                      <ExternalLink size={13} /> Live Demo
                    </a>
                  )}
                </div>
              </div>

              {/* Criteria Scoring Grid */}
              <div style={{ marginBottom: '1.5rem' }}>
                <h4 style={{ fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)', marginBottom: '0.75rem' }}>
                  Weighted Rubric Criteria
                </h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
                  {assignment.criteria.map((criterion) => (
                    <div
                      key={criterion.key}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '1rem',
                        padding: '0.75rem 1rem',
                        backgroundColor: 'var(--bg-subtle)',
                        borderRadius: 'var(--radius-md)',
                        border: '1px solid var(--border-subtle)',
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        <p style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                          {criterion.label}
                        </p>
                        {criterion.weight !== undefined && (
                          <p style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
                            weight: {criterion.weight}
                          </p>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: '0.3rem' }}>
                        {[1, 2, 3, 4, 5].map((val) => (
                          <button
                            key={val}
                            onClick={() => {
                              if (!assignment.finalized) {
                                setScores({ ...scores, [criterion.key]: val });
                              }
                            }}
                            disabled={assignment.finalized}
                            style={{
                              width: 36,
                              height: 36,
                              borderRadius: 'var(--radius-sm)',
                              border: scores[criterion.key] === val
                                ? '2px solid var(--accent)'
                                : '1px solid var(--border-subtle)',
                              backgroundColor: scores[criterion.key] === val
                                ? 'var(--accent-subtle)'
                                : 'var(--bg-surface)',
                              color: scores[criterion.key] === val
                                ? 'var(--accent)'
                                : 'var(--text-secondary)',
                              fontWeight: scores[criterion.key] === val ? 700 : 500,
                              fontSize: '0.875rem',
                              cursor: assignment.finalized ? 'not-allowed' : 'pointer',
                              transition: 'all 100ms ease',
                              opacity: assignment.finalized ? 0.6 : 1,
                            }}
                          >
                            {val}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Judge Comment */}
              <div style={{ marginBottom: '1.5rem' }}>
                <label style={{ fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)', display: 'block', marginBottom: '0.5rem' }}>
                  Judge Notes (Private)
                </label>
                <textarea
                  className="textarea"
                  rows={3}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  disabled={assignment.finalized}
                  placeholder="Internal review notes — not visible to participants."
                  style={{ resize: 'vertical', opacity: assignment.finalized ? 0.6 : 1 }}
                />
              </div>

              {saveMsg && (
                <div style={{
                  marginBottom: '1rem',
                  padding: '0.5rem 0.75rem',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.8125rem',
                  backgroundColor: saveMsg.includes('failed') ? 'var(--warning-subtle)' : 'var(--success-subtle)',
                  border: `1px solid ${saveMsg.includes('failed') ? 'var(--warning-border)' : 'var(--success-border)'}`,
                  color: saveMsg.includes('failed') ? 'var(--warning)' : 'var(--success)',
                }}>
                  {saveMsg}
                </div>
              )}

              {/* Actions */}
              <div style={{ display: 'flex', gap: '0.65rem' }}>
                <button
                  className="btn btn-secondary"
                  onClick={handleSave}
                  disabled={saving || assignment.finalized || !token}
                  style={{ opacity: (assignment.finalized || !token) ? 0.5 : 1 }}
                >
                  <Save size={14} />
                  <span>Save Draft</span>
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handleFinalize}
                  disabled={saving || assignment.finalized || !token}
                  style={{ opacity: (assignment.finalized || !token) ? 0.5 : 1 }}
                >
                  <Lock size={14} />
                  <span>Finalize & Lock into Audit Chain</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
