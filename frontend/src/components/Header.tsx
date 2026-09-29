import React from 'react';
import {
  Layers,
  Scale,
  BarChart3,
  Vote,
  ShieldCheck,
  Activity,
  Sun,
  Moon,
  ExternalLink,
} from 'lucide-react';

export type TabType = 'gallery' | 'judge' | 'results' | 'voting' | 'proofs' | 'progress';

interface HeaderProps {
  activeTab: TabType;
  onSelectTab: (tab: TabType) => void;
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
  eventTitle: string;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  onSelectTab,
  theme,
  onToggleTheme,
  eventTitle,
}) => {
  return (
    <header className="app-header">
      <div className="header-inner">
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          <div className="header-brand">
            <div className="brand-symbol">S</div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span className="brand-title">Samepage</span>
            </div>
            <span className="brand-event-badge">{eventTitle || 'Sample Hack 2026'}</span>
          </div>

          <nav className="nav-links" aria-label="Main Navigation">
            <button
              className={`nav-item ${activeTab === 'gallery' ? 'active' : ''}`}
              onClick={() => onSelectTab('gallery')}
            >
              <Layers size={15} />
              <span>Submissions</span>
            </button>

            <button
              className={`nav-item ${activeTab === 'judge' ? 'active' : ''}`}
              onClick={() => onSelectTab('judge')}
            >
              <Scale size={15} />
              <span>Judge Console</span>
            </button>

            <button
              className={`nav-item ${activeTab === 'results' ? 'active' : ''}`}
              onClick={() => onSelectTab('results')}
            >
              <BarChart3 size={15} />
              <span>REML Results</span>
            </button>

            <button
              className={`nav-item ${activeTab === 'voting' ? 'active' : ''}`}
              onClick={() => onSelectTab('voting')}
            >
              <Vote size={15} />
              <span>Quadratic Voting</span>
            </button>

            <button
              className={`nav-item ${activeTab === 'proofs' ? 'active' : ''}`}
              onClick={() => onSelectTab('proofs')}
            >
              <ShieldCheck size={15} />
              <span>Merkle Proofs</span>
            </button>

            <button
              className={`nav-item ${activeTab === 'progress' ? 'active' : ''}`}
              onClick={() => onSelectTab('progress')}
            >
              <Activity size={15} />
              <span>Organizer Progress</span>
            </button>
          </nav>
        </div>

        <div className="header-actions">
          <a
            href="http://193.36.236.221:21500/docs"
            target="_blank"
            rel="noreferrer"
            className="btn btn-secondary btn-sm"
            title="Inspect OpenAPI 3.0 Interactive Swagger Docs"
          >
            <span>Swagger API</span>
            <ExternalLink size={12} />
          </a>

          <button
            onClick={onToggleTheme}
            className="theme-toggle-btn"
            aria-label="Toggle Theme"
            title={`Switch to ${theme === 'light' ? 'Dark' : 'Light'} Mode`}
          >
            {theme === 'light' ? <Moon size={15} /> : <Sun size={15} />}
          </button>
        </div>
      </div>
    </header>
  );
};
