import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
  ApiError,
  DEMO_ACCOUNTS,
  DEMO_PASSWORD,
  backendUrl,
  get,
  post,
  signIn,
} from './lib/api';
import type {
  Account,
  Assignment,
  EventDetail,
  EventRow,
  Progress,
  Project,
  QueueItem,
  Results,
  Role,
  Team,
} from './lib/api';
import { Link, navigate } from './lib/router';
import { AssignPanel } from './settings';

// ---------- Small helpers ----------

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setError(null);
    load()
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, reload };
}

export function Failure({ error }: { error: ApiError | Error }) {
  const status = error instanceof ApiError ? error.status : 0;
  if (status === 401)
    return (
      <p className="banner">
        Sign in to see this page. <Link href="/">Sign in</Link>
      </p>
    );
  if (status === 403)
    return <p className="banner">Refused by the server (403): {error.message} Your role cannot see this page.</p>;
  if (status === 0 || status >= 500)
    return <p className="banner danger">The portal did not answer ({error.message}). Is the backend running?</p>;
  return <p className="banner">{error.message}</p>;
}

function Loading() {
  return <p className="meta">Loading…</p>;
}

export function State({ value }: { value: string }) {
  return <span className={`state ${value.replace(/\s+/g, '-')}`}>{value}</span>;
}

export function RolePill({ role }: { role: string }) {
  return <span className={`role ${role}`}>{role}</span>;
}

function PageHead({ kicker, title, children, aside }: { kicker?: string; title: string; children?: ReactNode; aside?: ReactNode }) {
  return (
    <header className="page">
      <div>
        {kicker && <p className="kicker">{kicker}</p>}
        <h1>{title}</h1>
        {children}
      </div>
      {aside && <div className="tools">{aside}</div>}
    </header>
  );
}

function Csv({ href, label = 'CSV' }: { href: string; label?: string }) {
  return (
    <a className="mono-link" href={backendUrl(href)} target="_blank" rel="noreferrer">
      {label}
    </a>
  );
}

// ---------- Sign-in ----------

const ROLE_NOTES: Record<Role, string> = {
  participant: 'Your team, your project and its deadline.',
  judge: 'Your judging console: the projects assigned to you.',
  organizer: "The event's control panel: progress, judges, results.",
  admin: 'The admin panel: every event, and new ones.',
};

export function SignIn({ onSignedIn }: { onSignedIn: (landing: string) => void }) {
  const [role, setRole] = useState<Role>('participant');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [picked, setPicked] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      onSignedIn(await signIn(email.trim(), password, role));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="signin">
      <div className="form-side">
        <p className="kicker">Samepage · submission and judging portal</p>
        <h1>Sign in</h1>
        <p className="lede">Pick your role and sign in. You land on that role's own panel.</p>
        {error && (
          <p className="banner" role="alert">
            {error}
          </p>
        )}
        <form onSubmit={submit}>
          <span className="label">Role</span>
          <div className="roles" role="radiogroup" aria-label="Role">
            {(['participant', 'judge', 'organizer', 'admin'] as Role[]).map((r) => (
              <label key={r} className={role === r ? 'on' : ''}>
                <input type="radio" name="role" value={r} checked={role === r} onChange={() => setRole(r)} />
                {r[0].toUpperCase() + r.slice(1)}
              </label>
            ))}
          </div>
          <p className="role-note">{ROLE_NOTES[role]}</p>
          <label>
            Email
            <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Password
            <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <button type="submit" className="primary wide" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="after">
          <span>
            No account? <a href={backendUrl('/signup')}>Create one</a>
          </span>
          <Link href="/e">Browse as a visitor →</Link>
        </p>
      </div>
      <aside className="demo-side" aria-label="Demo accounts">
        <h2>Demo accounts</h2>
        <p>
          This is the evaluation build. Every account's password is <code>{DEMO_PASSWORD}</code>. Pick one to fill in the form.
        </p>
        <ul className="accounts">
          {DEMO_ACCOUNTS.map((a) => (
            <li key={a.email}>
              <button
                type="button"
                aria-pressed={picked === a.email}
                onClick={() => {
                  setPicked(a.email);
                  setEmail(a.email);
                  setPassword(DEMO_PASSWORD);
                  setRole(a.role);
                }}
              >
                <span className="r">{a.label}</span>
                <span className="e">{a.email}</span>
                <span className="w">{a.note}</span>
              </button>
            </li>
          ))}
        </ul>
        <p className="fine">In production mode (SAMEPAGE_MODE=production) these accounts do not exist and this password is refused.</p>
      </aside>
    </section>
  );
}

// ---------- Admin panel and workspace ----------

export function AdminPanel() {
  const events = useLoad(() => get<{ items: EventRow[] }>('/e.json'), []);
  if (events.error) return <Failure error={events.error} />;
  if (!events.data) return <Loading />;
  const items = events.data.items;
  const count = (state: string) => items.filter((e) => e.state === state).length;
  return (
    <>
      <PageHead kicker="Admin panel" title="Every event on this portal" aside={<Link className="button primary" href="/e/new">New event</Link>} />
      <dl className="stats">
        <div><dt>Events</dt><dd>{items.length}</dd></div>
        <div><dt>Open</dt><dd>{count('open')}</dd></div>
        <div><dt>Judging</dt><dd>{count('judging')}</dd></div>
        <div><dt>Published</dt><dd>{count('published')}</dd></div>
      </dl>
      <EventTable items={items} admin />
    </>
  );
}

function EventTable({ items, admin = false }: { items: EventRow[]; admin?: boolean }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th>Event</th><th>State</th><th>Submissions close (UTC)</th><th>Your role</th><th></th></tr>
        </thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id}>
              <td><Link href={`/e/${e.id}`}>{e.name}</Link> <span className="id">{e.id}</span></td>
              <td><State value={e.state} /></td>
              <td className="mono">{e.submissions_close}</td>
              <td>{e.your_roles ? e.your_roles.split(' ').map((r) => <RolePill key={r} role={r} />) : <span className="meta">none</span>}</td>
              <td className="go">
                {admin && <><Link href={`/e/${e.id}/progress`}>Control panel</Link> · </>}
                <Link href={`/e/${e.id}/projects`}>Gallery</Link>
              </td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={5}>No events yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export function EventsList() {
  const events = useLoad(() => get<{ items: EventRow[] }>('/e.json'), []);
  if (events.error) return <Failure error={events.error} />;
  if (!events.data) return <Loading />;
  return (
    <>
      <PageHead kicker="Public" title="Events" aside={<Csv href="/e.csv" />} />
      <EventTable items={events.data.items} />
    </>
  );
}

export function Workspace({ me }: { me: Account }) {
  const events = useLoad(() => get<{ items: EventRow[] }>('/e.json'), []);
  const queue = useLoad(async () => {
    const judged = [...new Set(me.items.filter((i) => i.role === 'judge').map((i) => i.event_id))];
    const counts: Record<string, number> = {};
    for (const evt of judged) {
      const q = await get<{ open: number }>(`/e/${evt}/judge/batches.json`).catch(() => ({ open: 0 }));
      counts[evt] = q.open;
    }
    return counts;
  }, [me.id]);
  if (events.error) return <Failure error={events.error} />;
  if (!events.data) return <Loading />;
  const mine = events.data.items.filter((e) => e.your_roles || e.your_team);
  const others = events.data.items.filter((e) => !(e.your_roles || e.your_team));
  return (
    <>
      <PageHead kicker="My workspace" title="Your events">
        <p className="meta">Signed in as {me.email}.</p>
      </PageHead>
      {mine.length === 0 && <p className="banner">You have no role in any event yet. Open an event below and start a team, or ask an organizer for an invitation.</p>}
      <div className="workspaces">
        {mine.map((e) => {
          const roles = e.your_roles.split(' ').filter(Boolean);
          const staff = roles.includes('organizer') || roles.includes('admin');
          const judge = roles.includes('judge');
          return (
            <article className="workspace" key={e.id}>
              <header><span className="kicker">{e.id}</span><State value={e.state} /></header>
              <h3>{e.name}</h3>
              <p>{roles.map((r) => <RolePill key={r} role={r} />)}</p>
              <p className="meta mono">Closes {e.submissions_close}</p>
              {judge && <p>{queue.data?.[e.id] ?? '…'} review{queue.data?.[e.id] === 1 ? '' : 's'} waiting for you.</p>}
              <div className="actions">
                {staff && <Link className="button primary" href={`/e/${e.id}/progress`}>Open control panel</Link>}
                {judge && <Link className="button primary" href={`/e/${e.id}/judge/batches`}>Open judge console</Link>}
                {e.your_team && <Link className="button primary" href={`/e/${e.id}/teams/${e.your_team}`}>My team</Link>}
                <Link className="button" href={`/e/${e.id}/projects`}>Gallery</Link>
              </div>
            </article>
          );
        })}
      </div>
      {others.length > 0 && (
        <>
          <h2>Other events</h2>
          <EventTable items={others} />
        </>
      )}
    </>
  );
}

// ---------- Organizer: lifecycle and control panel ----------

const STEPS = ['draft', 'open', 'closed', 'judging', 'published'];

export function Lifecycle({ evt }: { evt: string }) {
  const settings = useLoad(() => get<EventDetail>(`/e/${evt}/settings.json`), [evt]);
  const [error, setError] = useState('');
  if (!settings.data) return null;
  const state = settings.data.state;
  const reached = STEPS.indexOf(state);
  const move = async (to: string) => {
    setError('');
    try {
      await post(`/e/${evt}/state.json`, { state: to });
      settings.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className="lifecycle">
      <span className="group">Event state</span>
      <ol>
        {STEPS.map((s, i) => (
          <li key={s} className={i === reached ? 'now' : i < reached ? 'done' : ''}>{s}</li>
        ))}
      </ol>
      {(settings.data.next_states || []).map((to) => (
        <button key={to} className="small" onClick={() => move(to)}>Move to {to}</button>
      ))}
      {state === 'judging' && <Link href={`/e/${evt}/results`}>Publish from Results →</Link>}
      {error && <span className="error">{error}</span>}
    </div>
  );
}

export function ControlPanel({ evt }: { evt: string }) {
  const progress = useLoad(() => get<Progress>(`/e/${evt}/progress.json`), [evt]);
  const [note, setNote] = useState('');
  if (progress.error) return <Failure error={progress.error} />;
  if (!progress.data) return <Loading />;
  const p = progress.data;
  const metric = (key: string) => p.metrics.find((m) => m.key === key);
  const confirm = async (dup: string) => {
    setNote('');
    try {
      await post(`/e/${evt}/duplicates/${dup}/confirm.json`, { resolution: 'keep_latest' });
      setNote(`${dup} confirmed as keep-latest. Results can now be published.`);
      progress.reload();
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    }
  };
  const numberLink = (key: string, text: string) => {
    const m = metric(key);
    return m ? <a href={backendUrl(m.href)} target="_blank" rel="noreferrer">{text}</a> : <span>{text}</span>;
  };
  return (
    <>
      <PageHead kicker="Control panel" title="Progress" aside={<Csv href={p.download_csv} label="Download CSV" />} />
      {p.provisional.map((dup) => (
        <p className="banner" key={dup}>
          Duplicate <strong>{dup}</strong> is resolved keep-latest but not confirmed, so publishing is refused (409) until a person confirms it.{' '}
          <button className="small" onClick={() => confirm(dup)}>Confirm keep-latest</button>
        </p>
      ))}
      {note && <p className="banner ok">{note}</p>}
      <p className="sentence">
        {numberLink('counted', `${p.sentence.counted} counted`)} + {numberLink('excluded', `${p.sentence.excluded} excluded`)} = {p.sentence.total}
      </p>
      <p className="sentence small">
        {p.sentence.fully_reviewed}/{p.sentence.active} fully reviewed · {p.sentence.short} short · {p.sentence.withdrawn_duplicate} withdrawn duplicate
      </p>
      <p className="recount">
        {p.recount.matched} of {p.recount.total} numbers on this page match the row count of the CSV they link to (each CSV is rendered and parsed on this request).
      </p>
      <h2>Assign</h2>
      <AssignPanel evt={evt} onDone={progress.reload} />
      <h2>Judges</h2>
      <p className="meta">
        Open work first: a judge with open assignments is behind. <Link href={`/e/${evt}/settings`}>Invite a judge →</Link>
      </p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Judge</th><th>Assigned</th><th>Finalized</th><th>Open</th><th>Drafts</th><th>Abandoned</th></tr></thead>
          <tbody>
            {p.judges.map((j) => (
              <tr key={j.judge_id} className={j.behind === 'true' ? 'behind' : ''}>
                <td>{j.name} <span className="id">{j.judge_id}</span></td>
                <td>{j.assigned}</td><td>{j.finalized}</td><td>{j.open}</td><td>{j.drafts}</td><td>{j.abandoned}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>Batches</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Batch</th><th>Judge</th><th>State</th><th>Done</th></tr></thead>
          <tbody>
            {p.batches.map((b) => (
              <tr key={b.id}>
                <td className="mono">{b.id}</td><td>{b.judge}</td><td><State value={b.state} /></td><td>{b.completed}/{b.assigned}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function ResultsView({ evt, staff }: { evt: string; staff: boolean }) {
  const results = useLoad(() => get<Results>(`/e/${evt}/results.json`), [evt]);
  const [note, setNote] = useState('');
  if (results.error) {
    if (results.error instanceof ApiError && results.error.status === 403)
      return (
        <>
          <PageHead kicker="Results" title="Not published yet" />
          <p className="banner">The server refuses the results (403) until an organizer publishes them. Judges and participants see the same.</p>
        </>
      );
    return <Failure error={results.error} />;
  }
  if (!results.data) return <Loading />;
  const r = results.data;
  const publish = async () => {
    setNote('');
    try {
      await post(`/e/${evt}/publish.json`);
      setNote('Published. The results are now public and frozen.');
      results.reload();
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <>
      <PageHead
        kicker={r.published ? `Published ${r.published_at}` : 'Results · visible to organizers only'}
        title="Results"
        aside={<Csv href={r.download_csv} label="Download CSV" />}
      />
      <p>{r.story}</p>
      <p className="meta mono">method {r.method}{r.lambda != null ? ` · λ ${Number(r.lambda).toFixed(3)}` : ''}{r.banner ? ` · ${r.banner}` : ''}</p>
      {staff && !r.published && (
        <div className="callout">
          <div>
            <strong>Publish results</strong>
            <p className="meta">Publishing freezes the ranking and makes it public. {r.open_duplicates.length > 0 && `Refused (409) while ${r.open_duplicates.join(', ')} is unconfirmed; confirm it on Progress first.`}</p>
          </div>
          <button className="primary" onClick={publish}>Publish results</button>
        </div>
      )}
      {note && <p className="banner">{note}</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Rank</th><th>Project</th><th>Track</th><th>Adjusted</th><th>Raw mean</th><th>Raptors k=10</th><th>Reviews</th></tr></thead>
          <tbody>
            {r.items.map((row) => (
              <tr key={row.id}>
                <td className="mono">{row.rank}{row.rank_lo !== row.rank_hi ? <span className="id"> ({row.rank_lo}–{row.rank_hi})</span> : null}</td>
                <td>{row.title} <span className="id">{row.id}</span></td>
                <td className="mono">{row.track}</td>
                <td className="mono strong">{row.adjusted}</td>
                <td className="mono">{row.raw_mean}</td>
                <td className="mono">{row.raptors_k10}</td>
                <td>{row.n_reviews}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ---------- Judge ----------

export function Queue({ evt }: { evt: string }) {
  const queue = useLoad(() => get<{ open: number; items: QueueItem[]; download_csv: string }>(`/e/${evt}/judge/batches.json`), [evt]);
  if (queue.error) return <Failure error={queue.error} />;
  if (!queue.data) return <Loading />;
  const q = queue.data;
  return (
    <>
      <PageHead kicker="Judge console" title="Your queue" aside={<Csv href={q.download_csv} />}>
        <p className="meta">{q.open} to finish. Only your own assignments are listed; anyone else's scores are refused by the server.</p>
      </PageHead>
      {q.items.length === 0 ? (
        <p className="banner">No batch assigned to you yet. An organizer issues batches from the event's control panel.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Project</th><th>Track</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {q.items.map((item) => (
                <tr key={item.project_id}>
                  <td><Link href={`/e/${evt}/judge/assignments/${item.project_id}`}>{item.title}</Link> <span className="id">{item.project_id}</span></td>
                  <td className="mono">{item.track}</td>
                  <td><State value={item.status === 'final' ? 'final' : 'to score'} /></td>
                  <td className="go">
                    {item.status === 'final' ? (
                      <Link href={`/e/${evt}/judge/assignments/${item.project_id}`}>View</Link>
                    ) : (
                      <Link className="button primary small" href={`/e/${evt}/judge/assignments/${item.project_id}`}>Score →</Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function Score({ evt, prj }: { evt: string; prj: string }) {
  const sheet = useLoad(() => get<Assignment>(`/e/${evt}/judge/assignments/${prj}.json`), [evt, prj]);
  const [values, setValues] = useState<Record<string, number>>({});
  const [comment, setComment] = useState('');
  const [note, setNote] = useState<{ text: string; ok: boolean } | null>(null);
  useEffect(() => {
    if (!sheet.data) return;
    const v: Record<string, number> = {};
    for (const c of sheet.data.criteria) if (c.value !== '' && c.value != null) v[c.key] = Number(c.value);
    setValues(v);
    setComment(sheet.data.comment || '');
  }, [sheet.data]);
  if (sheet.error) return <Failure error={sheet.error} />;
  if (!sheet.data) return <Loading />;
  const a = sheet.data;
  const send = async (final: boolean) => {
    setNote(null);
    try {
      const path = `/e/${evt}/judge/assignments/${prj}/${final ? 'finalize' : 'scores'}.json`;
      await post(path, { criteria: values, comment });
      setNote({ text: final ? 'Finalized. This review now counts in the results.' : 'Draft saved. It does not count until you finalize.', ok: true });
      sheet.reload();
    } catch (e) {
      setNote({ text: e instanceof Error ? e.message : String(e), ok: false });
    }
  };
  return (
    <>
      <PageHead kicker={`${a.track} · ${a.project_id}`} title={a.title} aside={<Link href={`/e/${evt}/judge/batches`}>All my projects</Link>}>
        <p>{a.tagline}</p>
      </PageHead>
      {a.description && <p>{a.description}</p>}
      <p className="meta">
        {a.repo_url && <><a href={a.repo_url} target="_blank" rel="noreferrer nofollow">repo</a> · </>}
        {a.live_url && <><a href={a.live_url} target="_blank" rel="noreferrer nofollow">live</a> · </>}
        {a.video_url && <><a href={a.video_url} target="_blank" rel="noreferrer nofollow">video</a> · </>}
        <Link href={`/e/${evt}/projects`}>gallery</Link>
      </p>
      <section className="score-panel">
        <header>
          <span className="kicker">Your score</span>
          <State value={a.finalized ? 'final' : `${a.state}, not yet final`} />
        </header>
        {a.criteria.map((c) => (
          <div className="criterion" key={c.key}>
            <span className="label">{c.label}</span>
            <div className="scale" role="radiogroup" aria-label={c.label}>
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  aria-pressed={values[c.key] === n}
                  disabled={a.finalized}
                  onClick={() => setValues((v) => ({ ...v, [c.key]: n }))}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        ))}
        <label>
          Comment
          <textarea value={comment} disabled={a.finalized} onChange={(e) => setComment(e.target.value)} />
        </label>
        {note && <p className={`banner ${note.ok ? 'ok' : ''}`}>{note.text}</p>}
        {!a.finalized && (
          <div className="row">
            <button className="primary" onClick={() => send(false)}>Save draft</button>
            <button onClick={() => send(true)}>Finalize</button>
          </div>
        )}
        <p className="meta">A draft is not counted in the results until you finalize it. The server only accepts scores for projects assigned to you.</p>
      </section>
    </>
  );
}

// ---------- Participant and public ----------

export function TeamView({ evt, team }: { evt: string; team: string }) {
  const data = useLoad(() => get<Team>(`/e/${evt}/teams/${team}.json`), [evt, team]);
  if (data.error) return <Failure error={data.error} />;
  if (!data.data) return <Loading />;
  const t = data.data;
  return (
    <>
      <PageHead kicker={`Team ${t.id}`} title={t.name} />
      <div className="grid2">
        <section className="card">
          <p className="kicker">Members ({t.members.length} of {t.max_team_size})</p>
          <ul className="plain">
            {t.members.map((m) => (
              <li key={m.person_id}>{m.name} <span className="id">{m.email}</span></li>
            ))}
          </ul>
        </section>
        <section className="card">
          <p className="kicker">Submission</p>
          {t.submission ? (
            <p><strong>{t.submission.title}</strong> <span className="id">{t.submission.id}</span> <State value={t.submission.state} /></p>
          ) : (
            <p>No submission yet.</p>
          )}
          {t.closed === 'true' ? (
            <p className="meta">Submissions are closed, so the team and its project are fixed. The server refuses edits after the deadline.</p>
          ) : (
            <p className="row">
              <a className="button primary" href={backendUrl(t.submission ? `/e/${evt}/projects/${t.submission.id}/edit` : `/e/${evt}/projects/new`)} target="_blank" rel="noreferrer">
                {t.submission ? 'Edit the submission' : 'Start the submission'}
              </a>
              <a className="button" href={backendUrl(`/e/${evt}/teams/${team}`)} target="_blank" rel="noreferrer">Invite links</a>
            </p>
          )}
        </section>
      </div>
    </>
  );
}

export function Gallery({ evt }: { evt: string }) {
  const data = useLoad(() => get<{ items: Project[]; count: number; tracks: { id: string; name: string }[]; download_csv: string }>(`/e/${evt}/projects.json`), [evt]);
  const [q, setQ] = useState('');
  const [track, setTrack] = useState('');
  const items = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data.data?.items || []).filter(
      (p) => (!track || p.track === track) && (!needle || `${p.title} ${p.tagline} ${p.team_name || ''}`.toLowerCase().includes(needle)),
    );
  }, [data.data, q, track]);
  if (data.error) return <Failure error={data.error} />;
  if (!data.data) return <Loading />;
  return (
    <>
      <PageHead kicker="Public gallery" title="Projects" aside={<Csv href={data.data.download_csv} label="Download CSV" />} />
      <div className="filters">
        <input type="search" placeholder="Search names, taglines and teams" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={track} onChange={(e) => setTrack(e.target.value)}>
          <option value="">All tracks</option>
          {data.data.tracks.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      <p className="meta">{items.length} of {data.data.count} projects</p>
      <div className="cards">
        {items.map((p) => (
          <article className="card" key={p.id}>
            <p className="kicker">{p.track_name}</p>
            <h3>{p.title}</h3>
            <p>{p.tagline}</p>
            <p className="meta">{p.team_name ? `${p.team_name} · ` : ''}{p.state} · {p.n_reviews} reviews</p>
            <p className="id">{p.id}{p.repo_url && <> · <a href={p.repo_url} target="_blank" rel="noreferrer nofollow">repo</a></>}</p>
          </article>
        ))}
      </div>
    </>
  );
}

export function EventView({ evt }: { evt: string }) {
  const data = useLoad(() => get<EventDetail>(`/e/${evt}.json`), [evt]);
  if (data.error) return <Failure error={data.error} />;
  if (!data.data) return <Loading />;
  const e = data.data;
  return (
    <>
      <PageHead kicker={`${e.id} · ${e.state}`} title={e.name} />
      {e.description && <p>{e.description}</p>}
      <dl className="stats">
        <div><dt>Submissions close (UTC)</dt><dd className="mono small">{e.submissions_close}</dd></div>
        <div><dt>Accepting submissions</dt><dd>{e.submissions_open === 'true' ? 'yes' : 'no'}</dd></div>
        <div><dt>Team size</dt><dd>up to {e.max_team_size}</dd></div>
        <div><dt>Tracks</dt><dd>{e.tracks.length}</dd></div>
      </dl>
      <div className="grid2">
        <section className="card"><p className="kicker">Tracks</p><ul className="plain">{e.tracks.map((t) => <li key={t.id}>{t.name} <span className="id">{t.id}</span></li>)}</ul></section>
        <section className="card"><p className="kicker">Prizes</p><ul className="plain">{e.prizes.map((p) => <li key={p.id}>{p.name}</li>)}</ul></section>
      </div>
      <p className="row">
        <Link className="button primary" href={`/e/${evt}/projects`}>Open the gallery</Link>
        <Link className="button" href={`/e/${evt}/results`}>Results</Link>
      </p>
    </>
  );
}

export function NewEvent() {
  const [form, setForm] = useState({ name: '', submissions_close: '', tracks: 'Developer tools\nClimate', prizes: 'Grand prize', criteria: 'Impact: 2\nCraft: 1', max_team_size: '4' });
  const [error, setError] = useState('');
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const created = await post<{ id: string }>('/e.json', form);
      navigate(`/e/${created.id}/progress`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };
  return (
    <>
      <PageHead kicker="Admin panel" title="New event">
        <p className="meta">Times are UTC. The event starts as a draft; move it to open from its control panel.</p>
      </PageHead>
      {error && <p className="banner" role="alert">{error}</p>}
      <form className="card form" onSubmit={submit}>
        <label>Name<input required value={form.name} onChange={set('name')} /></label>
        <label>Submissions close (UTC)<input type="datetime-local" required value={form.submissions_close} onChange={set('submissions_close')} /></label>
        <div className="grid2">
          <label>Tracks, one per line<textarea value={form.tracks} onChange={set('tracks')} /></label>
          <label>Prize categories, one per line<textarea value={form.prizes} onChange={set('prizes')} /></label>
        </div>
        <label>Rubric: one criterion per line as <code>Name: weight</code><textarea value={form.criteria} onChange={set('criteria')} /></label>
        <label>Largest team<input type="number" min={1} value={form.max_team_size} onChange={set('max_team_size')} /></label>
        <button className="primary" type="submit">Create event</button>
      </form>
    </>
  );
}
