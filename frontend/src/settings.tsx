import { useState } from 'react';
import type { FormEvent } from 'react';
import { get, post } from './lib/api';
import type { EventDetail } from './lib/api';
import { Failure, RolePill, useLoad } from './views';

// The portal pages on the VPS, for what this app does not edit (dates, rubric, weights).
const PORTAL = import.meta.env.VITE_PORTAL_URL || 'http://193.36.236.221:21500';

interface Person {
  person_id: string;
  name: string;
  email: string;
  role: string;
  tracks: string;
  assigned: number;
  finalized: number;
  open: number;
  status: string;
}

interface InviteResult {
  email: string;
  role: string;
  status: string;
  new_account: boolean;
  password_link: string;
  accept_link: string;
}

export function SettingsView({ evt }: { evt: string }) {
  const settings = useLoad(() => get<EventDetail & { people: Person[] }>(`/e/${evt}/settings.json`), [evt]);
  const [form, setForm] = useState({ email: '', name: '', role: 'judge' });
  const [tracks, setTracks] = useState<string[]>([]);
  const [result, setResult] = useState<InviteResult | null>(null);
  const [error, setError] = useState('');
  if (settings.error) return <Failure error={settings.error} />;
  if (!settings.data) return <p className="meta">Loading…</p>;
  const s = settings.data;
  const invite = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setResult(null);
    try {
      const r = await post<InviteResult>(`/e/${evt}/people.json`, { ...form, tracks });
      setResult(r);
      setForm({ email: '', name: '', role: 'judge' });
      setTracks([]);
      settings.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };
  const trackName = (id: string) => s.tracks.find((t) => t.id === id)?.name || id;
  const toggle = (id: string, on: boolean) => setTracks((cur) => (on ? [...cur, id] : cur.filter((x) => x !== id)));
  return (
    <>
      <header className="page">
        <div>
          <p className="kicker">Control panel</p>
          <h1>Settings · {s.name}</h1>
          <p className="meta">
            Judges and organizers of this event. Dates, rubric and weights are edited on the{' '}
            <a href={`${PORTAL}/e/${evt}/settings`} target="_blank" rel="noreferrer">portal settings page ↗</a>.
          </p>
        </div>
      </header>
      <section className="card form">
        <p className="kicker">Invite a judge or organizer</p>
        {error && <p className="banner" role="alert">{error}</p>}
        {result && (
          <div className="banner ok">
            <p><strong>{result.email}</strong> added as {result.role} ({result.status}).</p>
            {result.password_link && (
              <p>
                New account: send them this one-time link to choose a password. It is shown once and nothing is emailed.
                <br />
                <a href={result.password_link} target="_blank" rel="noreferrer" className="mono-link">{result.password_link}</a>
              </p>
            )}
            {result.accept_link && (
              <p>
                This address already has an account: it becomes {result.role} after signing in and opening this link.
                <br />
                <a href={result.accept_link} target="_blank" rel="noreferrer" className="mono-link">{result.accept_link}</a>
              </p>
            )}
          </div>
        )}
        <form onSubmit={invite}>
          <div className="grid2">
            <label>Email<input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
            <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          </div>
          <label>
            Role
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="judge">judge</option>
              <option value="organizer">organizer</option>
            </select>
          </label>
          {form.role === 'judge' && (
            <fieldset className="checks">
              <legend>Tracks this judge scores (none ticked means all)</legend>
              {s.tracks.map((t) => (
                <label key={t.id} className="check">
                  <input type="checkbox" checked={tracks.includes(t.id)} onChange={(e) => toggle(t.id, e.target.checked)} />
                  {t.name}
                </label>
              ))}
            </fieldset>
          )}
          <button className="primary" type="submit">Add</button>
        </form>
      </section>
      <h2>Judges and organizers</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Person</th><th>Role</th><th>Status</th><th>Tracks</th><th>Assigned</th><th>Done</th><th>Open</th></tr>
          </thead>
          <tbody>
            {s.people.map((p) => (
              <tr key={`${p.person_id}-${p.role}`}>
                <td>{p.name} <span className="id">{p.email}</span></td>
                <td><RolePill role={p.role} /></td>
                <td>{p.status}</td>
                <td className="meta">{p.tracks ? p.tracks.split(' ').map(trackName).join(', ') : 'all'}</td>
                <td>{p.assigned}</td>
                <td>{p.finalized}</td>
                <td>{p.open}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function AssignPanel({ evt, onDone }: { evt: string; onDone: () => void }) {
  const [coverage, setCoverage] = useState('3');
  const [cap, setCap] = useState('12');
  const [judge, setJudge] = useState('');
  const [project, setProject] = useState('');
  const [note, setNote] = useState<{ text: string; ok: boolean } | null>(null);
  const run = async (label: string, path: string, body: unknown) => {
    setNote(null);
    try {
      await post(path, body);
      setNote({ text: `${label}: done. The run is recorded in the audit log.`, ok: true });
      onDone();
    } catch (e) {
      setNote({ text: `${label}: ${e instanceof Error ? e.message : String(e)}`, ok: false });
    }
  };
  return (
    <section className="card">
      <p className="kicker">Assign projects to judges</p>
      <p className="meta">Judges only get projects in their tracks, and conflicts of interest are enforced. The event must be in judging.</p>
      <div className="row">
        <label className="inline">Reviews per project<input type="number" min={1} max={10} value={coverage} onChange={(e) => setCoverage(e.target.value)} /></label>
        <label className="inline">Most per judge<input type="number" min={1} max={60} value={cap} onChange={(e) => setCap(e.target.value)} /></label>
        <button className="primary" onClick={() => run('Issue batches', `/e/${evt}/assignment-runs.json`, { kind: 'initial', coverage, cap })}>Issue batches</button>
        <button onClick={() => run('Top up', `/e/${evt}/assignment-runs.json`, { kind: 'topup' })}>Top up short projects</button>
      </div>
      <div className="row">
        <label className="inline">Judge id<input placeholder="jdg_08" value={judge} onChange={(e) => setJudge(e.target.value)} /></label>
        <label className="inline">Project id<input placeholder="prj_15" value={project} onChange={(e) => setProject(e.target.value)} /></label>
        <button onClick={() => run('Assign one', `/e/${evt}/assignments.json`, { judge, project })}>Assign one</button>
      </div>
      {note && <p className={`banner ${note.ok ? 'ok' : ''}`}>{note.text}</p>}
    </section>
  );
}
