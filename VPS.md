# Deploying Samepage Live Test Version on a VPS

This branch (`live`) is pre-configured for instant deployment on a VPS so judges and evaluators can interactively test all portal features with prebuilt accounts and mock data.

---

## 1. Quick Deploy on Any VPS (Docker)

On your VPS (Ubuntu, Debian, Fedora, Arch, etc.):

```bash
git clone -b live https://github.com/JavohirX/samepage.git
cd samepage
docker compose up -d
```

That's it!
- Starts PostgreSQL 16 and Gunicorn.
- Migrates the schema and installs Postgres deadline safety triggers.
- Seeds all mock data: 41 submissions, 30 judges, 126 reviews.
- Binds to `0.0.0.0:8080`, immediately accessible from any browser at:
  ```
  http://<YOUR_VPS_IP>:8080
  ```

---

## 2. Prebuilt Test Accounts

Every account has the password: **`samepage-demo`**

| Role | Email | Direct Button on Top Demo Bar | What to test |
|---|---|---|---|
| **Organizer** | `organizer@samepage.live` | **Organizer** | Progress dashboard, batch matcher, moderation queue, normalization lab, publish |
| **Judge (Console)** | `judge@samepage.live` | **Judge (Console)** | Has an active batch ready to score in the Judge Console (`/e/evt_01/judge/batches`) |
| **Judge A** | `marek.nowak@example.org` | **Judge A** | Fixture judge `jdg_08`, has open assignments |
| **Judge B** | `priya.nair@example.org` | **Judge B** | Fixture judge `jdg_03`, has open assignments |
| **Participant** | `participant@samepage.live` | **Participant** | Team NorthKiln (`tm_01`), project "Glass Signal" |
| **Participant (Open)** | `control@example.org` | **Participant (Open)** | Event `evt_02` with open deadline; test drafting and submitting |
| **Admin** | `admin@samepage.live` | **Admin** | Global system administrator, create new hackathon events |

> **Note**: In addition to the above, **all 30 fixture judges** (from `jdg_01` to `jdg_30`) and all fixture participants can log in with their respective fixture emails and password `samepage-demo`.

---

## 3. Interactive Walkthrough for Judges

### 1. Score in the Judge Console
1. Click **Judge (Console)** on the demo bar (or sign in as `judge@samepage.live`).
2. Click **Console** in the header navigation or open `/e/evt_01/judge/batches`.
3. Open any assigned project card.
4. Adjust the criterion score sliders/inputs, write an optional comment, and click **Save review**.
5. Click **Finalize review**.
6. *Result*: The score is immediately written to the append-only ledger, the progress dashboard recounts the review, and results refit dynamically on read!

### 2. Community Quadratic Voting (T3)
1. Navigate to `/e/evt_01/voting`.
2. Allocate quadratic credits (up to 25 credits, $\sum (\text{credits}^2) \le 25$) across projects.
3. Submit your ballot.
4. Visit `/e/evt_01/tally` to view the live quadratic ranking and voter credit statistics.

### 3. Public Comments & Moderation Queue (T3)
1. Open any project in the gallery (`/e/evt_01/projects/prj_01`).
2. Post a comment at the bottom.
3. Switch to **Organizer** and visit `/e/evt_01/comments`.
4. Review pending comments and click **Approve** or **Reject**.

### 4. Live Progress Dashboard & Row Verification (T2)
1. Switch to **Organizer** and open `/e/evt_01/progress`.
2. Observe how every aggregate metric links to its exact CSV (`scores.csv?counted=false`).
3. Click any number to download and audit the underlying database rows.

### 5. Normalization Lab (T2)
1. As Organizer, visit `/e/evt_01/normalization`.
2. Compare raw averages vs. z-scores vs. REML additive judge-bias adjustments vs. Raptors $k=10$ shrinkage.
3. Check the statistical tie band across top projects.

### 6. Vector SVG Award Certificates (T4)
1. Open `/e/evt_01/teams/tm_01/certificate.svg`.
2. Inspect the standalone vector certificate with embedded Ed25519 signature and verification hash.

### 7. Interactive API Documentation (T4)
1. Open `http://<YOUR_VPS_IP>:8080/docs`.
2. Test any OpenAPI 3.0 endpoint directly through Swagger UI.

---

## 4. Optional: Production Nginx Reverse Proxy (Ports 80 / 443)

If you want to run behind Nginx with your domain and SSL (Let's Encrypt):

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then run `certbot --nginx -d yourdomain.com` for free automatic HTTPS.
