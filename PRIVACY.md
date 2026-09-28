# Privacy

This build is a judging portal for one event's fixture, plus the accounts the seed creates.

- Passwords are hashed. Fixture accounts have an unusable password. Demo accounts share one hash of `samepage-demo`, which production mode refuses.
- Bearer tokens are stored as sha256. In demo mode the raw tokens are printed at boot.
- Judge comments are visible to that judge and to organizers, not to participants or visitors.
- Team member emails are not on the public project page.
- When blind judging is on, judges do not receive the team name or team id from the gallery in HTML, JSON or CSV.
- The gallery shows each project's review count to everyone.
- Logs hold the request line, status, client address and a correlation id. Nothing is sent anywhere.
- There is no analytics beacon and no third-party font or script. Pico CSS and `console.js` are files we serve.
- There is no retention or deletion tooling yet. An operator deletes rows with SQL.
