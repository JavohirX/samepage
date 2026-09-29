// The portal's JSON API. Every request goes to the same origin under /api/backend, which
// Vercel (vercel.json) and the Vite dev server (vite.config.ts) forward to the Django app, so
// the session cookie the backend sets on sign-in is sent back on every later call.

const BASE = import.meta.env.VITE_API_URL || '/api/backend';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function backendUrl(path: string): string {
  return BASE + path;
}

function problemText(body: unknown, fallback: string): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === 'string') return b.detail;
    if (b.errors && typeof b.errors === 'object') {
      return Object.entries(b.errors as Record<string, unknown>)
        .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : String(v)}`)
        .join('; ');
    }
    if (typeof b.title === 'string') return b.title;
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (init.body) headers['Content-Type'] = 'application/json';
  const res = await fetch(BASE + path, { credentials: 'include', ...init, headers });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    throw new ApiError(res.status, problemText(body, `${res.status} ${res.statusText}`));
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
}

export const get = <T>(path: string) => request<T>(path);
export const post = <T>(path: string, body: unknown = {}) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) });

// ---------- Accounts ----------

export type Role = 'participant' | 'judge' | 'organizer' | 'admin';

export interface Account {
  id: string;
  email: string;
  name: string;
  is_admin: string;
  items: { event_id: string; event: string; role: string; team_id: string }[];
}

export async function getAccount(): Promise<Account | null> {
  try {
    return await get<Account>('/account.json');
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return null;
    throw err;
  }
}

function decodeHtml(text: string): string {
  const el = document.createElement('textarea');
  el.innerHTML = text;
  return el.value;
}

/** Signs in with the backend's own /login. It answers 303 to the role's landing page, which
 * fetch follows, so the final URL's path is where this role lands. */
export async function signIn(email: string, password: string, role: Role): Promise<string> {
  const res = await fetch(BASE + '/login', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'text/html' },
    body: JSON.stringify({ email, password, role }),
  });
  if (res.status === 401 || res.status === 403 || res.status === 429) {
    const html = await res.text();
    const found = html.match(/role="alert">([^<]*)</);
    const fallback = res.status === 429 ? 'Too many attempts; wait a minute.' : 'Those credentials were refused.';
    throw new ApiError(res.status, found ? decodeHtml(found[1]) : fallback);
  }
  if (!res.ok && !res.redirected) throw new ApiError(res.status, `Sign-in failed (${res.status}).`);
  if (!res.redirected) return '/';
  const landing = new URL(res.url).pathname;
  return landing.startsWith(BASE) ? landing.slice(BASE.length) || '/' : landing;
}

export async function signOut(): Promise<void> {
  await fetch(BASE + '/logout', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });
}

// ---------- Payloads ----------

export interface EventRow {
  id: string;
  name: string;
  state: string;
  submissions_close: string;
  your_roles: string;
  your_team: string;
}

export interface EventDetail {
  id: string;
  name: string;
  description: string;
  state: string;
  submissions_close: string;
  submissions_open: string;
  max_team_size: number;
  tracks: { id: string; name: string }[];
  prizes: { id: string; name: string }[];
  next_states?: string[];
}

export interface Progress {
  sentence: {
    counted: number;
    excluded: number;
    total: number;
    fully_reviewed: number;
    active: number;
    short: number;
    withdrawn_duplicate: number;
  };
  metrics: { key: string; value: number; label: string; href: string; csv_rows: number; matches_csv: string }[];
  recount: { matched: number; total: number };
  provisional: string[];
  batches: { id: string; judge_id: string; judge: string; state: string; completed: number; assigned: number; stalled: string }[];
  judges: { judge_id: string; name: string; assigned: number; finalized: number; open: number; drafts: number; abandoned: number; behind: string }[];
  download_csv: string;
}

export interface ResultRow {
  id: string;
  title: string;
  rank: number;
  rank_lo: number;
  rank_hi: number;
  adjusted: string;
  raw_mean: string;
  raptors_k10: string;
  n_reviews: number;
  track: string;
  flags: string;
}

export interface Results {
  method: string;
  lambda: number | null;
  banner: string;
  story: string;
  items: ResultRow[];
  published: boolean;
  published_at: string;
  open_duplicates: string[];
  download_csv: string;
}

export interface QueueItem {
  project_id: string;
  title: string;
  track: string;
  batch_state: string;
  status: string;
}

export interface Assignment {
  title: string;
  project_id: string;
  tagline: string;
  description: string;
  repo_url: string;
  live_url: string;
  video_url: string;
  track: string;
  criteria: { key: string; label: string; value: string | number }[];
  comment: string;
  state: string;
  finalized: boolean;
  judging_ends: string;
}

export interface Team {
  id: string;
  name: string;
  members: { person_id: string; name: string; email: string }[];
  max_team_size: number;
  submission: { id: string; title: string; state: string } | null;
  closed: string;
}

export interface Project {
  id: string;
  title: string;
  tagline: string;
  track: string;
  track_name: string;
  team_name?: string;
  state: string;
  repo_url: string;
  n_reviews: number;
}

export const DEMO_ACCOUNTS: { label: string; email: string; role: Role; note: string }[] = [
  { label: 'Admin', email: 'admin@example.org', role: 'admin', note: "Creates events; every event's control panel" },
  { label: 'Organizer', email: 'organizer@example.org', role: 'organizer', note: 'Runs evt_01: progress, judges, results' },
  { label: 'Judge A', email: 'marek.nowak@example.org', role: 'judge', note: 'Two open reviews in the console' },
  { label: 'Judge B', email: 'priya.nair@example.org', role: 'judge', note: "Try Judge A's scores: refused with 403" },
  { label: 'Participant', email: 'priya1@example.org', role: 'participant', note: 'On a team in evt_01, which is closed' },
  { label: 'Participant (open event)', email: 'control@example.org', role: 'participant', note: 'evt_02 takes submissions' },
];

export const DEMO_PASSWORD = 'samepage-demo';
