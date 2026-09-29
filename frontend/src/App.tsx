import { useCallback, useEffect, useState } from 'react';
import { DEMO_ACCOUNTS, DEMO_PASSWORD, getAccount, signIn, signOut } from './lib/api';
import type { Account } from './lib/api';
import { Link, match, navigate, usePath } from './lib/router';
import {
  AdminPanel,
  ControlPanel,
  EventView,
  EventsList,
  Gallery,
  Lifecycle,
  NewEvent,
  Queue,
  ResultsView,
  RolePill,
  Score,
  SignIn,
  TeamView,
  Workspace,
} from './views';
import { SettingsView } from './settings';

function rolesIn(me: Account | null, evt: string | null): string[] {
  if (!me) return [];
  const roles = new Set(me.items.filter((i) => i.event_id === evt).map((i) => i.role));
  if (me.is_admin === 'true') roles.add('admin');
  return ['admin', 'organizer', 'judge', 'participant'].filter((r) => roles.has(r));
}

export function App() {
  const path = usePath();
  const [me, setMe] = useState<Account | null | undefined>(undefined);
  const [switchError, setSwitchError] = useState('');

  const refreshMe = useCallback(async () => {
    try {
      setMe(await getAccount());
    } catch {
      setMe(null);
    }
  }, []);
  useEffect(() => {
    refreshMe();
  }, [refreshMe]);

  const landed = async (landing: string) => {
    await refreshMe();
    navigate(landing);
  };
  const switchTo = async (email: string, role: (typeof DEMO_ACCOUNTS)[number]['role']) => {
    setSwitchError('');
    try {
      await landed(await signIn(email, DEMO_PASSWORD, role));
    } catch (e) {
      setSwitchError(e instanceof Error ? e.message : String(e));
    }
  };
  const leave = async () => {
    await signOut();
    setMe(null);
    navigate('/');
  };

  const found = path.match(/^\/e\/([^/]+)/);
  const evt = found && found[1] !== 'new' ? found[1] : null;
  const roles = rolesIn(me ?? null, evt);
  const staff = roles.includes('admin') || roles.includes('organizer');
  const judge = roles.includes('judge');
  const team = me?.items.find((i) => i.event_id === evt && i.team_id)?.team_id;
  const isAdmin = me?.is_admin === 'true';
  const onSignIn = !me && (path === '/' || path === '/login');

  let page;
  let m: Record<string, string> | null;
  if (me === undefined) page = <p className="meta">Loading…</p>;
  else if (path === '/' || path === '/login') page = me ? (isAdmin ? <AdminPanel /> : <Workspace me={me} />) : <SignIn onSignedIn={landed} />;
  else if (path === '/e') page = <EventsList />;
  else if (path === '/e/new') page = <NewEvent />;
  else if ((m = match('/e/:evt/progress', path))) page = <ControlPanel evt={m.evt} />;
  else if ((m = match('/e/:evt/settings', path))) page = <SettingsView evt={m.evt} />;
  else if ((m = match('/e/:evt/results', path))) page = <ResultsView evt={m.evt} staff={staff} />;
  else if ((m = match('/e/:evt/judge/batches', path))) page = <Queue evt={m.evt} />;
  else if ((m = match('/e/:evt/judge/assignments/:prj', path))) page = <Score evt={m.evt} prj={m.prj} />;
  else if ((m = match('/e/:evt/teams/:team', path))) page = <TeamView evt={m.evt} team={m.team} />;
  else if ((m = match('/e/:evt/projects', path))) page = <Gallery evt={m.evt} />;
  else if ((m = match('/e/:evt', path))) page = <EventView evt={m.evt} />;
  else page = <p className="banner">No page at {path}. <Link href="/">Go home</Link></p>;

  return (
    <div className="shell">
      {!onSignIn && (
        <aside className="demo-strip" aria-label="Demo accounts">
          <span className="label">Demo</span>
          {DEMO_ACCOUNTS.map((a) => (
            <button key={a.email} title={`${a.email}: ${a.note}`} aria-current={me?.email === a.email} onClick={() => switchTo(a.email, a.role)}>
              {a.label}
            </button>
          ))}
          {switchError && <span className="error">{switchError}</span>}
          <span className="hint">one click switches account · password {DEMO_PASSWORD}</span>
        </aside>
      )}
      <header className="top">
        <div className="brand">
          <Link className="home" href="/"><span className="mark" aria-hidden="true" />Samepage</Link>
          {evt && <Link className="event-pill" href={`/e/${evt}`}>{evt}</Link>}
        </div>
        <nav aria-label="Account">
          {me ? (
            <>
              <Link href="/">{isAdmin ? 'Admin panel' : 'My workspace'}</Link>
              <Link href="/e">Events</Link>
              <span className="who">
                {(evt ? roles : isAdmin ? ['admin'] : []).map((r) => <RolePill key={r} role={r} />)}
                <span className="email">{me.email}</span>
              </span>
              <button onClick={leave}>Sign out</button>
            </>
          ) : (
            <>
              <Link href="/e">Events</Link>
              {!onSignIn && <Link className="button primary" href="/">Sign in</Link>}
            </>
          )}
        </nav>
      </header>
      {evt && (
        <nav className="tabs" aria-label="Event">
          {staff && (
            <>
              <span className="group">Control panel</span>
              <Link href={`/e/${evt}/progress`}>Progress</Link>
              <Link href={`/e/${evt}/results`}>Results</Link>
              <Link href={`/e/${evt}/settings`}>Settings</Link>
              <span className="sep" />
            </>
          )}
          {judge && (
            <>
              <span className="group">Judge</span>
              <Link href={`/e/${evt}/judge/batches`}>Console</Link>
              <span className="sep" />
            </>
          )}
          {team && (
            <>
              <span className="group">My team</span>
              <Link href={`/e/${evt}/teams/${team}`}>Team and submission</Link>
              <span className="sep" />
            </>
          )}
          <span className="group">Public</span>
          <Link href={`/e/${evt}`}>Event</Link>
          <Link href={`/e/${evt}/projects`}>Gallery</Link>
          {!staff && <Link href={`/e/${evt}/results`}>Results</Link>}
        </nav>
      )}
      {evt && staff && <Lifecycle evt={evt} />}
      <main className="container">{page}</main>
      <footer className="site">
        <span>Samepage · every number opens as the rows behind it</span>
        <span>HTML, JSON and CSV from one policy check</span>
      </footer>
    </div>
  );
}

export default App;
