import React from 'react';
import { User, ShieldCheck, Scale, Award, Terminal } from 'lucide-react';
import { DEMO_PERSONAS } from '../lib/api';
import type { Persona } from '../lib/types';

interface PersonaBarProps {
  currentPersona: Persona;
  onSelectPersona: (persona: Persona) => void;
  apiConnected: boolean;
}

export const PersonaBar: React.FC<PersonaBarProps> = ({
  currentPersona,
  onSelectPersona,
  apiConnected,
}) => {
  const getIcon = (id: string) => {
    switch (id) {
      case 'organizer':
        return <ShieldCheck size={13} />;
      case 'judge_a':
      case 'judge_b':
        return <Scale size={13} />;
      case 'participant':
        return <Award size={13} />;
      default:
        return <User size={13} />;
    }
  };

  return (
    <div className="persona-strip">
      <div className="persona-strip-left">
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', fontWeight: 600 }}>
          <Terminal size={14} /> Demo Persona:
        </span>
        <span style={{ color: 'var(--text-tertiary)' }}>|</span>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
          {currentPersona.description}
        </span>
      </div>

      <div className="persona-strip-pills">
        {DEMO_PERSONAS.map((p) => {
          const isActive = p.id === currentPersona.id;
          return (
            <button
              key={p.id}
              className={`persona-pill ${isActive ? 'active' : ''}`}
              onClick={() => onSelectPersona(p)}
              title={`${p.name} (${p.email})`}
            >
              {getIcon(p.id)}
              <span>{p.roleLabel}</span>
            </button>
          );
        })}

        <div style={{ marginLeft: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              backgroundColor: apiConnected ? 'var(--success)' : 'var(--warning)',
              display: 'inline-block',
            }}
          />
          <span style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
            {apiConnected ? 'LIVE BACKEND' : 'OFFLINE FIXTURE'}
          </span>
        </div>
      </div>
    </div>
  );
};
