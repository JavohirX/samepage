# Vercel Frontend Setup & Integration Guide

This guide walks you through deploying your frontend on **Vercel** and connecting it seamlessly to the **Samepage** backend running on your VPS.

---

## 1. Backend Service Details

The backend is currently running live in an isolated Docker container on your VPS:

- **Base URL**: `http://193.36.236.221:21500`
- **Port**: `21500` *(isolated from other projects on the server)*
- **OpenAPI 3.0 Schema**: `http://193.36.236.221:21500/openapi.json`
- **Interactive Swagger Docs**: `http://193.36.236.221:21500/docs`
- **Health / Readiness Check**: `http://193.36.236.221:21500/readyz` (`{"ok": true}`)

---

## 2. Overcoming Mixed Content (HTTPS -> HTTP)

Because Vercel automatically deploys frontends over **HTTPS** (`https://<your-project>.vercel.app`), modern web browsers will block direct client-side JavaScript `fetch()` calls to an unencrypted `http://` IP address due to **Mixed Content Security Policies**.

### Recommended Solution: Vercel / Next.js Server-Side Rewrites

Configure your frontend to proxy API calls server-side. This keeps all browser traffic on `https://` and routes the request to the backend with zero CORS or Mixed Content issues:

### For Next.js (`next.config.js` or `next.config.mjs`)
```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/backend/:path*',
        destination: 'http://193.36.236.221:21500/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
```

### For Vite / React / Vue / SvelteKit (`vercel.json`)
If you are deploying a static SPA on Vercel:
```json
{
  "rewrites": [
    {
      "source": "/api/backend/:path*",
      "destination": "http://193.36.236.221:21500/:path*"
    },
    {
      "source": "/(.*)",
      "destination": "/index.html"
    }
  ]
}
```

Now in your frontend code, simply make requests to `/api/backend/...` (e.g. `/api/backend/e/evt_01/projects.json`), which works seamlessly over HTTPS.

---

## 3. Environment Variables in Vercel

In your Vercel Dashboard (**Project Settings -> Environment Variables**):

| Variable Name | Value (When Using Rewrites) | Value (When Calling Directly) |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `/api/backend` | `http://193.36.236.221:21500` |
| `VITE_API_URL` | `/api/backend` | `http://193.36.236.221:21500` |

---

## 4. Authentication & Test Credentials

The backend supports both **Session Cookies** and **Bearer Tokens**. For frontend client apps, **Bearer Tokens** are the easiest and most reliable method.

### 4.1 Ready-to-Use Demo Bearer Tokens (Instant API Auth)
Pass this in your HTTP request headers: `Authorization: Bearer <TOKEN>`

| Role | Person Email | Bearer Token |
|---|---|---|
| **👑 Organizer** | `organizer@samepage.live` | `sp_demo_org_6ffc79cd07cf2395bf305af7958f537287d840fb34ccd179c94cf52c4363280d` |
| **⚖️ Judge (Console)** | `judge@samepage.live` | `sp_demo_jdg08_db077fb394e3374f22839475b7a21522ebd009a64115c803fb6d15ed38d404ad` |
| **⚖️ Judge B** | `priya.nair@example.org` | `sp_demo_jdg03_f056283662f6dcf9d3872b94365d55317f61eeb5bbfd79a227b739372e5c07b3` |
| **🚀 Participant** | `participant@samepage.live` | `sp_demo_priya1_f85c87c220a901c9a55d13584dd11d8b6210c2f150fec88d33d00f1464fa94df` |

### 4.2 Standard Login Credentials
All pre-seeded demo accounts share the password: **`samepage-demo`**

| Role | Email | Password |
|---|---|---|
| **Organizer** | `organizer@samepage.live` | `samepage-demo` |
| **Judge (Console)** | `judge@samepage.live` | `samepage-demo` |
| **Judge A** | `marek.nowak@example.org` | `samepage-demo` |
| **Judge B** | `priya.nair@example.org` | `samepage-demo` |
| **Participant** | `participant@samepage.live` | `samepage-demo` |
| **Participant (Open evt_02)** | `control@example.org` | `samepage-demo` |
| **Admin** | `admin@samepage.live` | `samepage-demo` |

*(All 30 fixture judges `jdg_01` through `jdg_30` are also passworded to `samepage-demo`)*.

---

## 5. Key REST API Endpoints Map

Every route on Samepage supports dual formats: appending `.json` returns clean JSON payloads.

### 5.1 Public Endpoints (No Auth Needed)
| Endpoint | Method | Description |
|---|---|---|
| `/readyz` | `GET` | Health and database readiness check (`{"ok": true}`) |
| `/openapi.json` | `GET` | Complete OpenAPI 3.0 specification |
| `/e/evt_01/projects.json` | `GET` | List of all 41 submissions with scores and tracks |
| `/e/evt_01/projects/<prj_id>.json` | `GET` | Specific project detail, video/image URLs, and repo links |
| `/e/evt_01/criteria.json` | `GET` | Judging criteria matrix and scoring weights |
| `/e/evt_01/records/root.json` | `GET` | RFC 9162 Merkle tree entries and Ed25519 signed root |
| `/e/evt_01/teams/<team_id>/certificate.svg` | `GET` | Cryptographic vector SVG certificate with digital signature |

### 5.2 Judge Endpoints (Require Judge Auth)
| Endpoint | Method | Description |
|---|---|---|
| `/e/evt_01/judge/batches.json` | `GET` | Batches assigned to current judge (shows unreviewed projects) |
| `/e/evt_01/judge/assignments/<prj_id>.json` | `GET` | Criterion scoring sheet for a specific project assignment |
| `/e/evt_01/judge/assignments/<prj_id>/scores.json` | `POST` | Save draft scores (`{"criterion_id": score, ...}`) |
| `/e/evt_01/judge/assignments/<prj_id>/finalize.json` | `POST` | Finalize review (locks scores into audit log) |

### 5.3 Community Quadratic Voting Endpoints
| Endpoint | Method | Description |
|---|---|---|
| `/e/evt_01/voting.json` | `GET` | Current voting window status, budget (25 credits), and ballot |
| `/e/evt_01/voting.json` | `POST` | Cast quadratic ballot: `{"lines": [{"submission_id": "prj_01", "credits": 4}]}` |
| `/e/evt_01/voting/tally.json` | `GET` | Aggregated quadratic voting tally (Organizer token required) |

### 5.4 Project Comments & Moderation Queue
| Endpoint | Method | Description |
|---|---|---|
| `/e/evt_01/projects/<prj_id>/comments.json` | `GET` | List approved comments for a project |
| `/e/evt_01/projects/<prj_id>/comments.json` | `POST` | Submit a comment (enters pending queue) |
| `/e/evt_01/comments.json` | `GET` | List pending comments queue (Organizer token required) |
| `/e/evt_01/comments/<cmt_id>/approve.json` | `POST` | Approve comment into public view |
| `/e/evt_01/comments/<cmt_id>/reject.json` | `POST` | Reject comment |

### 5.5 Organizer & Progress Endpoints (Require Organizer Auth)
| Endpoint | Method | Description |
|---|---|---|
| `/e/evt_01/progress.json` | `GET` | Live completion metrics, track coverage, and row counts |
| `/e/evt_01/scores.json` | `GET` | Complete cross-judge scoring matrix |
| `/e/evt_01/results.json` | `GET` | Normalized rankings (raw, z-score, REML shrinkage) |
| `/e/evt_01/normalization.json` | `GET` | Normalization lab comparing models |

---

## 6. TypeScript / React Example Client

Here is a ready-to-use API client wrapper for your frontend:

```typescript
// lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api/backend';

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

  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`API Error ${response.status}: ${errorBody}`);
  }

  return response.json();
}

// Example: Fetch projects in a React component
export async function getProjects() {
  return fetchFromBackend('/e/evt_01/projects.json');
}

// Example: Cast a quadratic vote
export async function submitVote(participantToken: string, lines: { submission_id: string; credits: number }[]) {
  return fetchFromBackend(
    '/e/evt_01/voting.json',
    {
      method: 'POST',
      body: JSON.stringify({ lines }),
    },
    participantToken
  );
}
```

---

## 7. Quick Smoke Test via Terminal

To verify the backend is reachable before deploying to Vercel:

```bash
# 1. Healthcheck
curl -i http://193.36.236.221:21500/readyz

# 2. Fetch projects list
curl -s http://193.36.236.221:21500/e/evt_01/projects.json | head -n 30

# 3. Test CORS preflight (simulating Vercel origin)
curl -i -X OPTIONS http://193.36.236.221:21500/e/evt_01/projects.json \
  -H "Origin: https://my-app.vercel.app" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization,content-type"

# 4. Fetch with Organizer Bearer token
curl -s -H "Authorization: Bearer sp_demo_org_6ffc79cd07cf2395bf305af7958f537287d840fb34ccd179c94cf52c4363280d" \
  http://193.36.236.221:21500/e/evt_01/progress.json
```
