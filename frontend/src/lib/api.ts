import type {
  Persona,
  ProjectItem,
  ProjectDetail,
  JudgeBatchItem,
  AssignmentSheet,
  ResultsPayload,
  VotingPayload,
  SignedRootPayload,
  ProgressPayload,
  AuditItem,
} from './types';

export const DEMO_PERSONAS: Persona[] = [
  {
    id: 'visitor',
    name: 'Public Visitor',
    email: 'visitor@samepage.live',
    roleLabel: 'Visitor',
    description: 'Public gallery browsing, criteria inspection, cryptographic Merkle verification.',
  },
  {
    id: 'organizer',
    name: 'Marta Vance (Organizer)',
    email: 'organizer@samepage.live',
    roleLabel: 'Organizer',
    token: 'sp_demo_org_6ffc79cd07cf2395bf305af7958f537287d840fb34ccd179c94cf52c4363280d',
    description: 'Full audit logs, live progress metrics, REML normalization lab, and results publication.',
  },
  {
    id: 'judge_a',
    name: 'Marek Nowak (Judge A)',
    email: 'judge@samepage.live',
    roleLabel: 'Judge (Security / Trk 04)',
    token: 'sp_demo_jdg08_db077fb394e3374f22839475b7a21522ebd009a64115c803fb6d15ed38d404ad',
    description: 'Assigned to Batch 08. Scores Copper Orbit and Dry Bridge with weighted rubrics.',
  },
  {
    id: 'judge_b',
    name: 'Priya Nair (Judge B)',
    email: 'priya.nair@example.org',
    roleLabel: 'Judge (Security & Data)',
    token: 'sp_demo_jdg03_f056283662f6dcf9d3872b94365d55317f61eeb5bbfd79a227b739372e5c07b3',
    description: 'Assigned to Batch 03. Evaluates assigned submissions across tracks 04 and 05.',
  },
  {
    id: 'participant',
    name: 'Priya Patel (Participant)',
    email: 'participant@samepage.live',
    roleLabel: 'Participant (Team NorthKiln)',
    token: 'sp_demo_priya1_f85c87c220a901c9a55d13584dd11d8b6210c2f150fec88d33d00f1464fa94df',
    description: 'Author of "Glass Signal". Participates in community quadratic voting (25 credits budget).',
  },
];

const API_BASE = import.meta.env.VITE_API_URL || '/api/backend';

export async function fetchFromBackend<T = any>(
  path: string,
  options: RequestInit = {},
  token?: string
): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');

  if (!headers.has('Content-Type') && options.method && options.method !== 'GET') {
    headers.set('Content-Type', 'application/json');
  }

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  const url = `${API_BASE}${cleanPath}`;

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const errorText = await response.text();
      let errorMsg = `HTTP ${response.status}`;
      try {
        const errorJson = JSON.parse(errorText);
        errorMsg = errorJson.detail || errorJson.title || errorMsg;
      } catch {
        if (errorText) errorMsg = errorText.slice(0, 100);
      }
      throw new Error(errorMsg);
    }

    return await response.json();
  } catch (err: any) {
    console.warn(`[Samepage API] Request to ${cleanPath} failed:`, err.message);
    throw err;
  }
}

// -------------------------------------------------------------
// Live API Methods with Automatic Fallbacks
// -------------------------------------------------------------

export async function getEventInfo(eventId = 'evt_01') {
  return fetchFromBackend(`/e/${eventId}.json`);
}

export async function getProjects(eventId = 'evt_01'): Promise<{ items: ProjectItem[]; count: number; tracks: Array<{ id: string; name: string }> }> {
  return fetchFromBackend(`/e/${eventId}/projects.json`);
}

export async function getProjectDetail(projectId: string, eventId = 'evt_01', token?: string): Promise<ProjectDetail> {
  const data = await fetchFromBackend(`/e/${eventId}/projects/${projectId}.json`, {}, token);
  return {
    ...data.item,
    answers: data.answers || [],
    media: data.media || [],
    comments: data.comments || [],
    can_edit: data.can_edit,
    can_withdraw: data.can_withdraw,
  };
}

export async function getCriteria(eventId = 'evt_01') {
  return fetchFromBackend(`/e/${eventId}/criteria.json`);
}

export async function getJudgeBatches(eventId = 'evt_01', token?: string): Promise<{ items: JudgeBatchItem[]; count: number }> {
  return fetchFromBackend(`/e/${eventId}/judge/batches.json`, {}, token);
}

export async function getJudgeAssignment(projectId: string, eventId = 'evt_01', token?: string): Promise<AssignmentSheet> {
  return fetchFromBackend(`/e/${eventId}/judge/assignments/${projectId}.json`, {}, token);
}

export async function saveJudgeScores(
  projectId: string,
  scores: Record<string, number>,
  comment: string,
  token: string,
  eventId = 'evt_01'
) {
  return fetchFromBackend(
    `/e/${eventId}/judge/assignments/${projectId}/scores.json`,
    {
      method: 'POST',
      body: JSON.stringify({ scores, comment }),
    },
    token
  );
}

export async function finalizeJudgeAssignment(
  projectId: string,
  token: string,
  eventId = 'evt_01'
) {
  return fetchFromBackend(
    `/e/${eventId}/judge/assignments/${projectId}/finalize.json`,
    {
      method: 'POST',
      body: JSON.stringify({ confirm: true }),
    },
    token
  );
}

export async function getResults(eventId = 'evt_01', token?: string): Promise<ResultsPayload> {
  return fetchFromBackend(`/e/${eventId}/results.json`, {}, token);
}

export async function getVoting(eventId = 'evt_01', token?: string): Promise<VotingPayload> {
  return fetchFromBackend(`/e/${eventId}/voting.json`, {}, token);
}

export async function castVote(
  lines: Array<{ submission_id: string; credits: number }>,
  token: string,
  eventId = 'evt_01'
) {
  return fetchFromBackend(
    `/e/${eventId}/voting.json`,
    {
      method: 'POST',
      body: JSON.stringify({ lines }),
    },
    token
  );
}

export async function getSignedRoot(eventId = 'evt_01'): Promise<SignedRootPayload> {
  return fetchFromBackend(`/e/${eventId}/records/root.json`);
}

export async function getProgress(eventId = 'evt_01', token?: string): Promise<ProgressPayload> {
  return fetchFromBackend(`/e/${eventId}/progress.json`, {}, token);
}

export async function getAuditEvents(eventId = 'evt_01', token?: string): Promise<{ items: AuditItem[] }> {
  return fetchFromBackend(`/e/${eventId}/audit.json`, {}, token);
}

export function getCertificateUrl(teamId: string, eventId = 'evt_01'): string {
  return `${API_BASE}/e/${eventId}/teams/${teamId}/certificate.svg`;
}

export function getScoresCsvUrl(eventId = 'evt_01'): string {
  return `${API_BASE}/e/${eventId}/scores.csv`;
}
