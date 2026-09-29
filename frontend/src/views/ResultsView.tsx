import React, { useState, useEffect } from 'react';
import { AlertCircle, Hash, ChevronDown, ChevronUp, ArrowUpDown } from 'lucide-react';
import type { ResultsPayload } from '../lib/types';
import { getResults } from '../lib/api';
import { FALLBACK_RESULTS } from '../lib/mockFallback';

interface ResultsViewProps {
  token?: string;
}

type SortKey = 'rank' | 'adjusted' | 'raw_mean' | 'n_reviews' | 'p_top5';

export const ResultsView: React.FC<ResultsViewProps> = ({ token }) => {
  const [results, setResults] = useState<ResultsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [noAuth, setNoAuth] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('rank');
  const [sortAsc, setSortAsc] = useState(true);

  useEffect(() => {
    getResults('evt_01', token)
      .then((data) => {
        setResults(data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.message?.includes('403') || err.message?.includes('HTTP 403')) {
          setNoAuth(true);
        }
        setResults(FALLBACK_RESULTS);
        setLoading(false);
      });
  }, [token]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(key === 'rank');
    }
  };

  const sortedItems = results
    ? [...results.items].sort((a, b) => {
        const av = Number((a as any)[sortKey]) || 0;
        const bv = Number((b as any)[sortKey]) || 0;
        return sortAsc ? av - bv : bv - av;
      })
    : [];

  const renderSortIcon = (col: SortKey) => {
    if (sortKey !== col) return <ArrowUpDown size={11} style={{ opacity: 0.3 }} />;
    return sortAsc ? <ChevronUp size={12} /> : <ChevronDown size={12} />;
  };

  const getRankMedal = (rank: number) => {
    if (rank === 1) return '🥇';
    if (rank === 2) return '🥈';
    if (rank === 3) return '🥉';
    return '';
  };

  if (loading) {
    return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-tertiary)' }}>Loading results...</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, letterSpacing: '-0.03em', marginBottom: '0.35rem' }}>
          REML-Normalized Rankings
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Woodbury profile restricted maximum likelihood with k=10 shrinkage, leave-one-judge-out credible intervals, and rank-draw probability.
        </p>
      </div>

      {noAuth && (
        <div style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--warning)', fontSize: '0.8125rem', padding: '0.65rem 0.85rem', backgroundColor: 'var(--warning-subtle)', border: '1px solid var(--warning-border)', borderRadius: 'var(--radius-md)' }}>
          <AlertCircle size={14} />
          <span>Results require <strong>Organizer</strong> authentication. Showing fixture data. Switch persona above.</span>
        </div>
      )}

      {results && (
        <>
          {/* Meta Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.75rem', marginBottom: '1.5rem' }}>
            <div className="card" style={{ padding: '1rem' }}>
              <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Method</p>
              <p style={{ fontSize: '1rem', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{results.method?.toUpperCase() || 'REML'}</p>
            </div>
            <div className="card" style={{ padding: '1rem' }}>
              <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Lambda (λ)</p>
              <p style={{ fontSize: '1rem', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{results.lambda || '—'}</p>
            </div>
            <div className="card" style={{ padding: '1rem' }}>
              <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Projects Ranked</p>
              <p style={{ fontSize: '1rem', fontWeight: 600 }}>{results.count}</p>
            </div>
            <div className="card" style={{ padding: '1rem' }}>
              <p style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}>Published</p>
              <p style={{ fontSize: '1rem', fontWeight: 600, color: results.published ? 'var(--success)' : 'var(--text-primary)' }}>
                {results.published ? 'Yes' : 'Pending'}
              </p>
            </div>
          </div>

          {results.ranking_sha256 && (
            <div style={{ marginBottom: '1.5rem', padding: '0.65rem 1rem', backgroundColor: 'var(--bg-subtle)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Hash size={13} color="var(--text-tertiary)" />
              <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', fontWeight: 500 }}>Ranking SHA-256:</span>
              <code style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', wordBreak: 'break-all' }}>
                {results.ranking_sha256}
              </code>
            </div>
          )}

          {/* Rankings Table */}
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 60, cursor: 'pointer' }} onClick={() => handleSort('rank')}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                      Rank {renderSortIcon('rank')}
                    </span>
                  </th>
                  <th>Project</th>
                  <th>Track</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => handleSort('adjusted')}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                      REML Adj. {renderSortIcon('adjusted')}
                    </span>
                  </th>
                  <th style={{ cursor: 'pointer' }} onClick={() => handleSort('raw_mean')}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                      Raw Mean {renderSortIcon('raw_mean')}
                    </span>
                  </th>
                  <th>95% CI</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => handleSort('n_reviews')}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                      Reviews {renderSortIcon('n_reviews')}
                    </span>
                  </th>
                  <th style={{ cursor: 'pointer' }} onClick={() => handleSort('p_top5')}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                      P(Top 5) {renderSortIcon('p_top5')}
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((item) => (
                  <tr key={item.id}>
                    <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', textAlign: 'center' }}>
                      {getRankMedal(item.rank)} {item.rank}
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: '0.875rem' }}>{item.title}</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>{item.id}</div>
                    </td>
                    <td><span className="badge">{item.track}</span></td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{item.adjusted}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{item.raw_mean}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      [{item.rank_lo}, {item.rank_hi}]
                    </td>
                    <td style={{ textAlign: 'center' }}>{item.n_reviews}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <div style={{
                          width: 60,
                          height: 5,
                          borderRadius: 3,
                          backgroundColor: 'var(--border-subtle)',
                          overflow: 'hidden',
                        }}>
                          <div style={{
                            width: `${Math.min(Number(item.p_top5) * 100, 100)}%`,
                            height: '100%',
                            backgroundColor: Number(item.p_top5) > 0.5 ? 'var(--accent)' : 'var(--text-tertiary)',
                            borderRadius: 3,
                            transition: 'width 300ms ease',
                          }} />
                        </div>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-secondary)', minWidth: 36 }}>
                          {(Number(item.p_top5) * 100).toFixed(1)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
};
