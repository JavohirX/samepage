# Privacy

This build is a judging portal for one event's fixture, plus the accounts the seed creates.

- Passwords are hashed. Fixture accounts have an unusable password. Demo accounts share one hash of `samepage-demo`.
- Bearer tokens are stored as sha256. The raw token is shown once, at boot, in demo mode.
- Invite tokens are stored as sha256.
- Judge comments are visible to that judge and to organizers, not to participants or visitors.
- Team member emails are not on the public project page.
- When blind judging is on, judges do not receive the team name or team id in HTML, JSON or CSV.
- There is no analytics beacon and no third-party font or script. Pico CSS and `console.js` are files we serve.
