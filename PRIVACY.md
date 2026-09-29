# Privacy

This build stores the accounts people create, the events, teams and submissions they make, and the fixture in demo mode.

- Passwords are hashed (PBKDF2). Fixture accounts and invited accounts have an unusable password until the person sets one. Demo accounts share one hash of `samepage-demo`, which production mode refuses.
- Invite, set-password and role acceptance links are stored as sha256 only.
- A draft submission and its images are visible to its team and the organizers only. Team member emails are visible to the team and the organizers.
- Uploaded images are stored in the database as uploaded (no metadata stripping).
- Bearer tokens are stored as sha256. In demo mode the raw tokens are printed at boot.
- Judge comments are visible to that judge and to organizers, not to participants or visitors.
- Team member emails are not on the public project page.
- When blind judging is on, judges do not receive the team name or team id from the gallery (in HTML, JSON or CSV) or from the project page.
- The gallery shows each project's review count to everyone.
- Logs hold the request line, status, client address and a correlation id. Nothing is sent anywhere.
- There is no analytics beacon and no third-party font or script. Pico CSS and `console.js` are files we serve.
- The audit log is append-only and keeps, for each write, the actor's id and the values before and after: submission titles, tags and URLs, invited email addresses, score values. The runtime database role cannot delete it.
- Organizers see the name and email of everyone with a role on their event and of every team member.
- There is no retention or deletion tooling yet. An operator deletes rows with SQL (the audit log only as the database owner).
