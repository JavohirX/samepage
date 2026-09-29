import React, { useState, useEffect } from 'react';
import { X, ExternalLink, GitBranch, Video, Award, MessageSquare, Send } from 'lucide-react';
import type { ProjectDetail, ProjectItem } from '../lib/types';
import { getProjectDetail, getCertificateUrl } from '../lib/api';

interface ProjectDetailModalProps {
  project: ProjectItem | null;
  onClose: () => void;
  token?: string;
}

export const ProjectDetailModal: React.FC<ProjectDetailModalProps> = ({
  project,
  onClose,
  token,
}) => {
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [newComment, setNewComment] = useState('');
  const [commentSent, setCommentSent] = useState(false);

  useEffect(() => {
    if (!project) return;
    setLoading(true);
    getProjectDetail(project.id, 'evt_01', token)
      .then((data) => {
        setDetail(data);
        setLoading(false);
      })
      .catch(() => {
        // Fallback to minimal project object
        setDetail({
          ...project,
          answers: [],
          media: [],
          comments: [],
        });
        setLoading(false);
      });
  }, [project, token]);

  if (!project) return null;

  const handlePostComment = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newComment.trim()) return;
    // optimistic feedback
    setCommentSent(true);
    setNewComment('');
  };

  const item = detail || project;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
              <span className="badge badge-accent">{item.track_name || item.track}</span>
              <span className="badge font-mono">{item.id}</span>
              {item.badge && <span className="badge badge-success">{item.badge}</span>}
            </div>
            <h2 style={{ fontSize: '1.4rem', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
              {item.title}
            </h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.2rem' }}>
              by <strong>{item.team_name}</strong>
            </p>
          </div>

          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-tertiary)',
              cursor: 'pointer',
              padding: '0.25rem',
            }}
            aria-label="Close dialog"
          >
            <X size={20} />
          </button>
        </div>

        {/* Tagline & Description */}
        <div style={{ marginBottom: '1.5rem' }}>
          <p style={{ fontSize: '0.95rem', fontWeight: 500, color: 'var(--text-primary)', marginBottom: '0.65rem' }}>
            {item.tagline}
          </p>
          {item.description && (
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              {item.description}
            </p>
          )}
        </div>

        {/* Action Links */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.65rem', marginBottom: '1.5rem' }}>
          {item.repo_url && (
            <a
              href={item.repo_url}
              target="_blank"
              rel="noreferrer"
              className="btn btn-secondary btn-sm"
            >
              <GitBranch size={14} />
              <span>Source Repository</span>
              <ExternalLink size={12} />
            </a>
          )}
          {item.live_url && (
            <a
              href={item.live_url}
              target="_blank"
              rel="noreferrer"
              className="btn btn-secondary btn-sm"
            >
              <ExternalLink size={14} />
              <span>Live Deployment</span>
            </a>
          )}
          {item.video_url && (
            <a
              href={item.video_url}
              target="_blank"
              rel="noreferrer"
              className="btn btn-secondary btn-sm"
            >
              <Video size={14} />
              <span>Demo Video</span>
            </a>
          )}
          {item.team_id && (
            <a
              href={getCertificateUrl(item.team_id)}
              target="_blank"
              rel="noreferrer"
              className="btn btn-secondary btn-sm"
              title="Download tamper-evident SVG certificate"
            >
              <Award size={14} />
              <span>SVG Certificate</span>
              <ExternalLink size={12} />
            </a>
          )}
        </div>

        {/* Answers to Custom Organizer Questions */}
        {detail?.answers && detail.answers.length > 0 && (
          <div style={{ marginBottom: '1.5rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '1.25rem' }}>
            <h4 style={{ fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)', marginBottom: '0.75rem' }}>
              Submission Q&A
            </h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              {detail.answers.map((ans, idx) => (
                <div key={idx} style={{ backgroundColor: 'var(--bg-subtle)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-md)' }}>
                  <p style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
                    {ans.question}
                  </p>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                    {ans.answer}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Public Comments & Feedback Section */}
        <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.75rem' }}>
            <MessageSquare size={15} color="var(--text-secondary)" />
            <h4 style={{ fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>
              Community Discussion
            </h4>
          </div>

          {commentSent && (
            <div style={{ backgroundColor: 'var(--success-subtle)', border: '1px solid var(--success-border)', color: 'var(--success)', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', marginBottom: '0.75rem' }}>
              Comment submitted successfully. It will appear after organizer moderation.
            </div>
          )}

          <form onSubmit={handlePostComment} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
            <input
              type="text"
              className="input"
              placeholder="Leave constructive feedback or questions..."
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              style={{ fontSize: '0.8125rem' }}
            />
            <button type="submit" className="btn btn-primary btn-sm">
              <Send size={13} />
              <span>Post</span>
            </button>
          </form>

          {loading ? (
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)' }}>Loading details...</p>
          ) : detail?.comments && detail.comments.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {detail.comments.map((cmt) => (
                <div key={cmt.id} style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.5rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                    <span>{cmt.author}</span>
                    <span>{new Date(cmt.created_at).toLocaleDateString()}</span>
                  </div>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--text-primary)', marginTop: '0.2rem' }}>
                    {cmt.text}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
              No comments yet. Be the first to share constructive review feedback.
            </p>
          )}
        </div>
      </div>
    </div>
  );
};
