import { useState, useEffect } from 'react';
import { Header } from './components/Header';
import type { TabType } from './components/Header';
import { PersonaBar } from './components/PersonaBar';
import { DEMO_PERSONAS, getEventInfo } from './lib/api';
import type { Persona } from './lib/types';
import { GalleryView } from './views/GalleryView';
import { JudgeView } from './views/JudgeView';
import { ResultsView } from './views/ResultsView';
import { VotingView } from './views/VotingView';
import { ProofsView } from './views/ProofsView';
import { ProgressView } from './views/ProgressView';
import { Shield, GitCommit, FileCode } from 'lucide-react';

export function App() {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('samepage_theme');
    if (saved === 'dark' || saved === 'light') return saved;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  });

  const [activeTab, setActiveTab] = useState<TabType>(() => {
    const hash = window.location.hash.replace('#', '') as TabType;
    const validTabs: TabType[] = ['gallery', 'judge', 'results', 'voting', 'proofs', 'progress'];
    return validTabs.includes(hash) ? hash : 'gallery';
  });

  const [currentPersona, setCurrentPersona] = useState<Persona>(DEMO_PERSONAS[0]);
  const [apiConnected, setApiConnected] = useState(false);
  const [eventTitle, setEventTitle] = useState('Sample Hack 2026');

  // Sync theme with DOM and localStorage
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('samepage_theme', theme);
  }, [theme]);

  // Sync tab with URL hash
  useEffect(() => {
    window.location.hash = activeTab;
  }, [activeTab]);

  // Check backend health and event title on load
  useEffect(() => {
    getEventInfo('evt_01')
      .then((data) => {
        setApiConnected(true);
        if (data.title) setEventTitle(data.title);
      })
      .catch(() => {
        setApiConnected(false);
      });
  }, []);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'light' ? 'dark' : 'light'));
  };

  const handleSelectPersona = (persona: Persona) => {
    setCurrentPersona(persona);
    // Smooth ergonomics: auto-navigate to relevant tab if switching to a specialized role
    if (persona.id.startsWith('judge') && activeTab === 'gallery') {
      setActiveTab('judge');
    } else if (persona.id === 'organizer' && activeTab === 'gallery') {
      setActiveTab('progress');
    } else if (persona.id === 'participant' && activeTab === 'gallery') {
      setActiveTab('voting');
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Interactive Demo Persona Strip */}
      <PersonaBar
        currentPersona={currentPersona}
        onSelectPersona={handleSelectPersona}
        apiConnected={apiConnected}
      />

      {/* Primary Sticky Header */}
      <Header
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        theme={theme}
        onToggleTheme={toggleTheme}
        eventTitle={eventTitle}
      />

      {/* Main Tabbed Views Container */}
      <div className="app-container" style={{ flex: 1, width: '100%' }}>
        <main className="main-content" role="main">
          {activeTab === 'gallery' && <GalleryView token={currentPersona.token} />}
          {activeTab === 'judge' && <JudgeView token={currentPersona.token} />}
          {activeTab === 'results' && <ResultsView token={currentPersona.token} />}
          {activeTab === 'voting' && <VotingView token={currentPersona.token} />}
          {activeTab === 'proofs' && <ProofsView />}
          {activeTab === 'progress' && (
            <ProgressView token={currentPersona.token} onNavigateTab={setActiveTab} />
          )}
        </main>
      </div>

      {/* Minimalist Editorial Footer */}
      <footer className="app-footer">
        <div className="footer-inner">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Samepage Hackathon Engine</span>
              <span style={{ color: 'var(--text-tertiary)' }}>·</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>v1.0.0-rc</span>
            </div>
            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
              Cryptographically verified peer consensus with Restricted Maximum Likelihood (REML) bias normalization.
            </p>
          </div>

          <div className="footer-links">
            <button
              onClick={() => setActiveTab('proofs')}
              style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
              className="footer-links"
            >
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-secondary)' }}>
                <Shield size={13} />
                <span>Merkle Proofs</span>
              </span>
            </button>

            <a
              href="http://193.36.236.221:21500/docs"
              target="_blank"
              rel="noreferrer"
              title="FastAPI Interactive Documentation"
            >
              <FileCode size={13} />
              <span>OpenAPI Specification</span>
            </a>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-tertiary)' }}>
              <GitCommit size={13} />
              <span style={{ fontFamily: 'var(--font-mono)' }}>Ed25519 Signed</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;
