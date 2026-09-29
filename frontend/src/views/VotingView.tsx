import React, { useState, useEffect } from 'react';
import { Minus, Plus, Send, AlertCircle, Info } from 'lucide-react';
import type { VotingPayload, VotingItem } from '../lib/types';
import { getVoting, castVote } from '../lib/api';
import { FALLBACK_VOTING } from '../lib/mockFallback';

interface VotingViewProps {
  token?: string;
}

export const VotingView: React.FC<VotingViewProps> = ({ token }) => {
  const [voting, setVoting] = useState<VotingPayload | null>(null);
  const [ballot, setBallot] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState('');

  const initBallot = (items: VotingItem[]) => {
    const init: Record<string, number> = {};
    items.forEach((item) => {
      init[item.project_id] = item.credits || 0;
    });
    setBallot(init);
  };

  useEffect(() => {
    if (!token) {
      setVoting(FALLBACK_VOTING);
      initBallot(FALLBACK_VOTING.items);
      setLoading(false);
      return;
    }
    getVoting('evt_01', token)
      .then((data) => {
        setVoting(data);
        initBallot(data.items);
        setLoading(false);
      })
      .catch(() => {
        setVoting(FALLBACK_VOTING);
        initBallot(FALLBACK_VOTING.items);
        setLoading(false);
      });
  }, [token]);

  const totalCreditsSpent = Object.values(ballot).reduce((sum, c) => sum + c, 0);
  const budget = voting?.credit_budget || 25;
  const remaining = budget - totalCreditsSpent;

  const getQuadraticVotes = (credits: number) => Math.sqrt(credits);

  const adjustCredit = (projectId: string, delta: number) => {
    const newVal = Math.max(0, (ballot[projectId] || 0) + delta);
    const otherSpent = totalCreditsSpent - (ballot[projectId] || 0);
    if (otherSpent + newVal > budget) return;
    setBallot({ ...ballot, [projectId]: newVal });
  };

  const handleSubmit = async () => {
    if (!token) {
      setSubmitMsg('Switch to a Participant persona to cast a real vote.');
      return;
    }
    setSubmitting(true);
    try {
      const lines = Object.entries(ballot)
        .filter(([, credits]) => credits > 0)
        .map(([submission_id, credits]) => ({ submission_id, credits }));
      await castVote(lines, token);
      setSubmitMsg('Ballot submitted successfully via quadratic voting.');
    } catch (err: any) {
      setSubmitMsg(`Vote failed: ${err.message}`);
    }
    setSubmitting(false);
  };

  if (loading) {
    return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-tertiary)' }}>Loading voting booth...</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, letterSpacing: '-0.03em', marginBottom: '0.35rem' }}>
          Quadratic Community Voting
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Distribute {budget} credits across projects. Cost of n votes = n² credits. Encourages broad preference signaling.
        </p>
      </div>

      {/* Budget & Mechanic Explainer */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.75rem', marginBottom: '1.5rem' }}>
        <div className="card" style={{ padding: '1rem' }}>
          <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Credit Budget</p>
          <p style={{ fontSize: '1.5rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{budget}</p>
        </div>
        <div className="card" style={{ padding: '1rem' }}>
          <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Credits Used</p>
          <p style={{ fontSize: '1.5rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: totalCreditsSpent > 0 ? 'var(--accent)' : 'var(--text-primary)' }}>
            {totalCreditsSpent}
          </p>
        </div>
        <div className="card" style={{ padding: '1rem' }}>
          <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Remaining</p>
          <p style={{ fontSize: '1.5rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: remaining === 0 ? 'var(--warning)' : 'var(--success)' }}>
            {remaining}
          </p>
        </div>
        <div className="card" style={{ padding: '1rem' }}>
          <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Voting Window</p>
          <p style={{ fontSize: '1rem', fontWeight: 600, color: voting?.state === 'open' ? 'var(--success)' : 'var(--text-primary)' }}>
            {voting?.state === 'open' ? 'Open' : 'Closed'}
          </p>
        </div>
      </div>

      {/* QV Explainer */}
      <div style={{ marginBottom: '1.5rem', padding: '0.75rem 1rem', backgroundColor: 'var(--accent-subtle)', border: '1px solid var(--accent-border)', borderRadius: 'var(--radius-md)', display: 'flex', gap: '0.5rem', alignItems: 'flex-start', fontSize: '0.8125rem', color: 'var(--accent)' }}>
        <Info size={15} style={{ marginTop: '0.1rem', flexShrink: 0 }} />
        <div>
          <strong>Quadratic voting mechanic:</strong> 1 credit = 1 vote, 4 credits = 2 votes, 9 credits = 3 votes, 16 credits = 4 votes.
          The square root diminishing return incentivizes spreading support rather than concentrating it.
        </div>
      </div>

      {voting?.voter?.excluded && (
        <div style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--warning)', fontSize: '0.8125rem', padding: '0.65rem 0.85rem', backgroundColor: 'var(--warning-subtle)', border: '1px solid var(--warning-border)', borderRadius: 'var(--radius-md)' }}>
          <AlertCircle size={14} />
          <span>This voter is excluded: <strong>{voting.voter.exclusion_reason?.replace(/_/g, ' ')}</strong></span>
        </div>
      )}

      {/* Ballot Grid */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', marginBottom: '1.5rem' }}>
        {voting?.items.map((item) => {
          const credits = ballot[item.project_id] || 0;
          const effectiveVotes = getQuadraticVotes(credits);
          return (
            <div
              key={item.project_id}
              className="card"
              style={{
                padding: '1rem 1.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '1rem',
                borderColor: credits > 0 ? 'var(--accent-border)' : undefined,
                backgroundColor: credits > 0 ? 'var(--accent-subtle)' : undefined,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.2rem' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{item.title}</span>
                  <span className="badge font-mono" style={{ fontSize: '0.65rem' }}>{item.project_id}</span>
                </div>
                {item.tagline && (
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.tagline}
                  </p>
                )}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexShrink: 0 }}>
                <div style={{ textAlign: 'center', minWidth: 55 }}>
                  <p style={{ fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)' }}>Votes</p>
                  <p style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '1.1rem', color: credits > 0 ? 'var(--accent)' : 'var(--text-tertiary)' }}>
                    {effectiveVotes.toFixed(1)}
                  </p>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => adjustCredit(item.project_id, -1)}
                    disabled={credits === 0}
                    style={{ width: 32, height: 32, padding: 0, opacity: credits === 0 ? 0.3 : 1 }}
                    aria-label={`Remove 1 credit from ${item.title}`}
                  >
                    <Minus size={14} />
                  </button>
                  <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.9rem', minWidth: 30, textAlign: 'center' }}>
                    {credits}
                  </span>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => adjustCredit(item.project_id, 1)}
                    disabled={remaining <= 0}
                    style={{ width: 32, height: 32, padding: 0, opacity: remaining <= 0 ? 0.3 : 1 }}
                    aria-label={`Add 1 credit to ${item.title}`}
                  >
                    <Plus size={14} />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {submitMsg && (
        <div style={{
          marginBottom: '1rem',
          padding: '0.5rem 0.75rem',
          borderRadius: 'var(--radius-sm)',
          fontSize: '0.8125rem',
          backgroundColor: submitMsg.includes('failed') || submitMsg.includes('Switch') ? 'var(--warning-subtle)' : 'var(--success-subtle)',
          border: `1px solid ${submitMsg.includes('failed') || submitMsg.includes('Switch') ? 'var(--warning-border)' : 'var(--success-border)'}`,
          color: submitMsg.includes('failed') || submitMsg.includes('Switch') ? 'var(--warning)' : 'var(--success)',
        }}>
          {submitMsg}
        </div>
      )}

      <button
        className="btn btn-primary"
        onClick={handleSubmit}
        disabled={submitting || totalCreditsSpent === 0}
        style={{ opacity: totalCreditsSpent === 0 ? 0.5 : 1 }}
      >
        <Send size={14} />
        <span>Cast Quadratic Ballot ({totalCreditsSpent} credits → {Object.values(ballot).reduce((s, c) => s + getQuadraticVotes(c), 0).toFixed(1)} votes)</span>
      </button>
    </div>
  );
};
