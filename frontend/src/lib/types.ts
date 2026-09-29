export type Role = 'visitor' | 'participant' | 'judge_a' | 'judge_b' | 'organizer' | 'admin';

export interface Persona {
  id: Role;
  name: string;
  email: string;
  roleLabel: string;
  token?: string;
  description: string;
}

export interface Track {
  id: string;
  name: string;
}

export interface Criterion {
  key: string;
  label: string;
  weight?: string | number;
  value?: string | number;
}

export interface ProjectItem {
  id: string;
  title: string;
  tagline: string;
  description?: string;
  track: string;
  track_name: string;
  team_id?: string;
  team_name: string;
  state: 'draft' | 'submitted' | 'withdrawn';
  repo_url?: string;
  live_url?: string;
  video_url?: string;
  tech_tags?: string;
  thumbnail?: string;
  submitted_at?: string;
  n_reviews?: number;
  badge?: string;
  position?: number;
  version?: number;
}

export interface ProjectDetail extends ProjectItem {
  answers?: Array<{ question_id: string; question: string; answer: string }>;
  media?: Array<{ id: number; url: string; caption?: string }>;
  comments?: Array<{ id: string; author: string; text: string; created_at: string; status: string }>;
  can_edit?: boolean;
  can_withdraw?: boolean;
}

export interface JudgeBatchItem {
  project_id: string;
  title: string;
  track: string;
  batch_id: string;
  batch_state: string;
  finalized: boolean | string;
  status: string;
}

export interface AssignmentSheet {
  title: string;
  event: string;
  project_id: string;
  tagline?: string;
  description?: string;
  repo_url?: string;
  live_url?: string;
  video_url?: string;
  track?: string;
  criteria: Criterion[];
  comment?: string;
  state?: string;
  batch_state?: string;
  finalized: boolean;
  judging_ends?: string;
}

export interface ResultItem {
  id: string;
  title: string;
  rank: number;
  rank_lo: number;
  rank_hi: number;
  adjusted: string;
  raw_mean: string;
  raptors_k10: string;
  n_reviews: number;
  p_top5: string;
  tie_group: number;
  track_rank: number;
  track: string;
  method?: string;
  flags?: string;
}

export interface ResultsPayload {
  title: string;
  event: string;
  method: string;
  lambda?: number | string;
  ranking_sha256?: string;
  published: boolean;
  published_at?: string;
  items: ResultItem[];
  count: number;
  banner?: string;
  story?: string;
  fallback_reason?: string;
  degraded?: boolean;
}

export interface VotingItem {
  project_id: string;
  title: string;
  tagline?: string;
  credits: number;
}

export interface VotingPayload {
  title: string;
  event: string;
  state: 'open' | 'closed';
  credit_budget: number;
  credits_spent: number;
  voter?: {
    type: string;
    channel: string;
    excluded: boolean;
    exclusion_reason?: string;
  };
  items: VotingItem[];
}

export interface SignedRootPayload {
  title: string;
  event: string;
  root_hash: string;
  leaf_count: number;
  publish_seq: number;
  signature_ed25519: string;
  public_key_pem: string;
  statement: string;
  verify_command: string;
  root_txt?: string;
  root_sig?: string;
  pub_pem?: string;
}

export interface ProgressSentence {
  counted: number;
  excluded: number;
  total: number;
  fully_reviewed: number;
  active: number;
  short: number;
  withdrawn_duplicate: number;
}

export interface ProgressMetric {
  key: string;
  value: number;
  label: string;
  href?: string;
  csv_rows?: number;
  matches_csv?: string;
}

export interface ProgressPayload {
  title: string;
  event: string;
  sentence: ProgressSentence;
  metrics: ProgressMetric[];
  items?: Array<{
    project_id: string;
    title: string;
    track: string;
    n_reviews: number;
    needed: number;
    status: string;
  }>;
}

export interface AuditItem {
  seq: number;
  timestamp: string;
  actor: string;
  role: string;
  action: string;
  target: string;
  prev_hash: string;
  entry_hash: string;
}
