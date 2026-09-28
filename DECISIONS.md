# Decisions

| # | Decision | Why |
|---|---|---|
| D1 | One view class per resource. The suffix or the body type picks the response. | A generated pair of views is more machinery than the product needs. |
| D2 | Suffixed URL patterns first, slug converters. | Otherwise `prj_01.json` is parsed as an id. |
| D3 | Errors are plain Django responses. | DRF would re-render a 403 through the CSV renderer and return 500. |
| D4 | No htmx, no SPA, no Node. | Pico and one small script. Pages work without JavaScript except autosave. |
| D5 | T3 is not in this build. | The checker does not score it, and a claimed-but-unverified tier is the expensive mistake. |
| D6 | The λ grid is part of the method. | Independent fits land on the same point only if they search the same places. The likelihood is flat. |
| D7 | Imported rows are exempt from the one-active-submission index. | The fixture has two active Dry Harbour rows for one team. Enforcing the index on import crashes the seed. |
| D8 | The runtime role is created on every boot and owns nothing. | Init scripts do not re-run on a reused volume. |
| D9 | Fixture people get an unusable password. Six demo principals share one hash. | Hashing every person at boot costs minutes. |
| D10 | Bearer tokens in `.dogfood.toml`, not cookies. | `run.py` then reaches the deadline check instead of a CSRF 403. |
| D11 | 403 before resolving a forbidden id. | A 404 fails the peer-score check and depends on whether the row exists. |
| D12 | Nothing is signed. | Stated in Limits. Detection is the audit chain plus a downloaded CSV. |
