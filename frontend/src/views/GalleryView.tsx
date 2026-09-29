import React, { useState, useEffect, useMemo } from 'react';
import { Search, Filter, ExternalLink, GitBranch, ChevronRight, Clock } from 'lucide-react';
import type { ProjectItem } from '../lib/types';
import { getProjects } from '../lib/api';
import { FALLBACK_PROJECTS } from '../lib/mockFallback';
import { ProjectDetailModal } from '../components/ProjectDetailModal';

interface GalleryViewProps {
  token?: string;
}

export const GalleryView: React.FC<GalleryViewProps> = ({ token }) => {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [tracks, setTracks] = useState<Array<{ id: string; name: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [trackFilter, setTrackFilter] = useState('');
  const [selectedProject, setSelectedProject] = useState<ProjectItem | null>(null);

  useEffect(() => {
    getProjects()
      .then((data) => {
        setProjects(data.items || []);
        setTracks(data.tracks || []);
        setLoading(false);
      })
      .catch(() => {
        setProjects(FALLBACK_PROJECTS);
        setTracks([
          { id: 'trk_01', name: 'Developer Tools' },
          { id: 'trk_02', name: 'Data & Analytics' },
          { id: 'trk_03', name: 'Accessibility' },
          { id: 'trk_04', name: 'Security' },
          { id: 'trk_08', name: 'Systems' },
        ]);
        setLoading(false);
      });
  }, []);

  const filtered = useMemo(() => {
    let result = projects;
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (p) =>
          p.title.toLowerCase().includes(q) ||
          p.tagline.toLowerCase().includes(q) ||
          (p.tech_tags || '').toLowerCase().includes(q) ||
          p.team_name.toLowerCase().includes(q)
      );
    }
    if (trackFilter) {
      result = result.filter((p) => p.track === trackFilter);
    }
    return result;
  }, [projects, search, trackFilter]);

  return (
    <div>
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, letterSpacing: '-0.03em', marginBottom: '0.35rem' }}>
          Submission Gallery
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          {projects.length} projects across {tracks.length} tracks — filterable by name, tagline, tags, or team.
        </p>
      </div>

      {/* Search & Filter Bar */}
      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1 1 280px' }}>
          <Search
            size={15}
            style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-tertiary)' }}
          />
          <input
            className="input"
            type="text"
            placeholder="Search projects by name, tagline, tags, or team..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ paddingLeft: '2.25rem' }}
          />
        </div>
        <div style={{ position: 'relative', flex: '0 0 200px' }}>
          <Filter
            size={14}
            style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-tertiary)' }}
          />
          <select
            className="select"
            value={trackFilter}
            onChange={(e) => setTrackFilter(e.target.value)}
            style={{ paddingLeft: '2.25rem' }}
          >
            <option value="">All Tracks</option>
            {tracks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Results Count */}
      <div style={{ marginBottom: '1rem', fontSize: '0.8125rem', color: 'var(--text-tertiary)' }}>
        Showing {filtered.length} of {projects.length} projects
        {trackFilter && ` in ${tracks.find((t) => t.id === trackFilter)?.name || trackFilter}`}
        {search && ` matching "${search}"`}
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-tertiary)' }}>
          Loading submissions from backend...
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-tertiary)' }}>
          No projects match your filters.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '1rem' }}>
          {filtered.map((project) => (
            <article
              key={project.id}
              className="card card-hover"
              style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}
              onClick={() => setSelectedProject(project)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter') setSelectedProject(project);
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                  <span className="badge badge-accent">{project.track_name}</span>
                  <span className="badge font-mono">{project.id}</span>
                  {project.badge && <span className="badge badge-success">{project.badge}</span>}
                </div>
                <ChevronRight size={16} color="var(--text-tertiary)" />
              </div>

              <div>
                <h3 style={{ fontSize: '1.05rem', fontWeight: 600, letterSpacing: '-0.01em', marginBottom: '0.2rem' }}>
                  {project.title}
                </h3>
                <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  {project.tagline}
                </p>
              </div>

              <div style={{ marginTop: 'auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                <span style={{ fontWeight: 500 }}>{project.team_name}</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  {project.n_reviews !== undefined && project.n_reviews > 0 && (
                    <span>{project.n_reviews} reviews</span>
                  )}
                  {project.submitted_at && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
                      <Clock size={11} />
                      {new Date(project.submitted_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', gap: '0.4rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.65rem' }}>
                {project.repo_url && (
                  <a
                    href={project.repo_url}
                    target="_blank"
                    rel="noreferrer"
                    className="btn btn-secondary btn-sm"
                    onClick={(e) => e.stopPropagation()}
                    style={{ fontSize: '0.75rem' }}
                  >
                    <GitBranch size={12} />
                    <span>Repo</span>
                  </a>
                )}
                {project.live_url && (
                  <a
                    href={project.live_url}
                    target="_blank"
                    rel="noreferrer"
                    className="btn btn-secondary btn-sm"
                    onClick={(e) => e.stopPropagation()}
                    style={{ fontSize: '0.75rem' }}
                  >
                    <ExternalLink size={12} />
                    <span>Live</span>
                  </a>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      <ProjectDetailModal
        project={selectedProject}
        onClose={() => setSelectedProject(null)}
        token={token}
      />
    </div>
  );
};
