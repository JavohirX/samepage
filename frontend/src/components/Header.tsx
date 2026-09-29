import React, { useState, useRef, useEffect } from 'react';
import {
  Layers,
  BarChart3,
  Scale,
  Vote,
  Activity,
  ShieldCheck,
  Sun,
  Moon,
  ExternalLink,
  ChevronDown,
  User,
  Award,
} from 'lucide-react';
import { DEMO_PERSONAS } from '../lib/api';
import type { Persona } from '../lib/types';

export type TabType = 'gallery' | 'results' | 'judge' | 'voting' | 'progress';

interface HeaderProps {
  activeTab: TabType;
  onSelectTab: (tab: TabType) => void;
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
  eventTitle: string;
  currentPersona: Persona;
  onSelectPersona: (persona: Persona) => void;
  onOpenProofs: () => void;
  apiConnected: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  onSelectTab,
  theme,
  onToggleTheme,
  eventTitle,
  currentPersona,
  onSelectPersona,
  onOpenProofs,
  apiConnected,
}) => {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const getPersonaIcon = (id: string) => {
    if (id === 'organizer') return <ShieldCheck size={13} />;
    if (id.startsWith('judge')) return <Scale size={13} />;
    if (id === 'participant') return <Award size={13} />;
    return <User size={13} />;
  };

  // Determine if a specialized role tab should be shown
  const isJudge = currentPersona.id.startsWith('judge');
  const isOrganizer = currentPersona.id === 'organizer';
  const isParticipant = currentPersona.id === 'participant';

  return (
    <header className="app-header">
      <div className="header-inner">
        {/* Left: Brand + Event Badge + Minimal Primary Tabs */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
          <div className="header-brand" style={{ cursor: 'pointer' }} onClick={() => onSelectTab('gallery')}>
            <div className="brand-symbol">S</div>
            <span className="brand-title">Samepage</span>
            <span className="brand-event-badge">{eventTitle || 'Sample Hack 2026'}</span>
          </div>

          <nav className="nav-links" aria-label="Main Navigation">
            <button
              className={`nav-item ${activeTab === 'gallery' ? 'active' : ''}`}
              onClick={() => onSelectTab('gallery')}
            >
              <Layers size={14} />
              <span>Submissions</span>
            </button>

            <button
              className={`nav-item ${activeTab === 'results' ? 'active' : ''}`}
              onClick={() => onSelectTab('results')}
            >
              <BarChart3 size={14} />
              <span>Leaderboard</span>
            </button>

            {/* Contextual Tab: Only visible when active role or tab warrants it */}
            {isJudge && (
              <button
                className={`nav-item ${activeTab === 'judge' ? 'active' : ''}`}
                onClick={() => onSelectTab('judge')}
                style={{
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-full)',
                  padding: '0.35rem 0.75rem',
                }}
              >
                <Scale size={14} color="var(--accent)" />
                <span style={{ fontWeight: 600 }}>Judge Console</span>
              </button>
            )}

            {isParticipant && (
              <button
                className={`nav-item ${activeTab === 'voting' ? 'active' : ''}`}
                onClick={() => onSelectTab('voting')}
                style={{
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-full)',
                  padding: '0.35rem 0.75rem',
                }}
              >
                <Vote size={14} color="var(--accent)" />
                <span style={{ fontWeight: 600 }}>Vote Ballot</span>
              </button>
            )}

            {isOrganizer && (
              <button
                className={`nav-item ${activeTab === 'progress' ? 'active' : ''}`}
                onClick={() => onSelectTab('progress')}
                style={{
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-full)',
                  padding: '0.35rem 0.75rem',
                }}
              >
                <Activity size={14} color="var(--accent)" />
                <span style={{ fontWeight: 600 }}>Operations</span>
              </button>
            )}
          </nav>
        </div>

        {/* Right: Actions, Proofs modal trigger, Theme, and Persona Dropdown */}
        <div className="header-actions">
          {/* Cryptographic Proofs Quick Modal Trigger */}
          <button
            onClick={onOpenProofs}
            className="btn btn-secondary btn-sm"
            title="Inspect RFC 9162 Merkle tree proofs & Ed25519 signature"
            style={{ fontSize: '0.75rem', gap: '0.35rem' }}
          >
            <ShieldCheck size={13} color="var(--success)" />
            <span>Verify Proofs</span>
          </button>

          <a
            href="http://193.36.236.221:21500/docs"
            target="_blank"
            rel="noreferrer"
            className="btn btn-secondary btn-sm"
            title="Inspect OpenAPI 3.0 Interactive Swagger Docs"
            style={{ fontSize: '0.75rem', gap: '0.35rem' }}
          >
            <span>API</span>
            <ExternalLink size={10} />
          </a>

          {/* Theme Toggle */}
          <button
            onClick={onToggleTheme}
            className="theme-toggle-btn"
            aria-label="Toggle Theme"
            title={`Switch to ${theme === 'light' ? 'Dark' : 'Light'} Mode`}
          >
            {theme === 'light' ? <Moon size={14} /> : <Sun size={14} />}
          </button>

          {/* Compact User / Persona Selector */}
          <div style={{ position: 'relative' }} ref={dropdownRef}>
            <button
              onClick={() => setDropdownOpen((prev) => !prev)}
              className="btn btn-secondary btn-sm"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.45rem',
                padding: '0.35rem 0.7rem',
                borderRadius: 'var(--radius-full)',
                fontWeight: 500,
                fontSize: '0.8rem',
              }}
              title="Switch demo persona / role"
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  backgroundColor: apiConnected ? 'var(--success)' : 'var(--warning)',
                  display: 'inline-block',
                }}
              />
              {getPersonaIcon(currentPersona.id)}
              <span>{currentPersona.roleLabel}</span>
              <ChevronDown size={12} color="var(--text-tertiary)" />
            </button>

            {dropdownOpen && (
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: 'calc(100% + 6px)',
                  width: '280px',
                  backgroundColor: 'var(--bg-surface)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  boxShadow: 'var(--shadow-md)',
                  padding: '0.5rem',
                  zIndex: 100,
                }}
              >
                <div
                  style={{
                    padding: '0.4rem 0.6rem 0.5rem 0.6rem',
                    borderBottom: '1px solid var(--border-subtle)',
                    marginBottom: '0.4rem',
                  }}
                >
                  <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)' }}>
                    Switch Demo Persona
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.15rem' }}>
                    Seamlessly test all access tiers
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                  {DEMO_PERSONAS.map((p) => {
                    const isSelected = p.id === currentPersona.id;
                    return (
                      <button
                        key={p.id}
                        onClick={() => {
                          onSelectPersona(p);
                          setDropdownOpen(false);
                        }}
                        style={{
                          textAlign: 'left',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.5rem',
                          padding: '0.45rem 0.6rem',
                          borderRadius: 'var(--radius-sm)',
                          border: 'none',
                          background: isSelected ? 'var(--accent-subtle)' : 'transparent',
                          color: isSelected ? 'var(--accent)' : 'var(--text-primary)',
                          cursor: 'pointer',
                          fontSize: '0.8rem',
                          fontWeight: isSelected ? 600 : 400,
                          transition: 'background 120ms ease',
                        }}
                      >
                        {getPersonaIcon(p.id)}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {p.name}
                          </div>
                          <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)' }}>
                            {p.roleLabel}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
