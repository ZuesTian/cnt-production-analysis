# Ali backend deployment

The production API runs on loopback port `8768` and is exposed through Caddy at:

`https://cnt-analysis.47.236.76.214.nip.io`

Persistent state lives under `/opt/cnt-production/data`; releases are immutable directories under `/opt/cnt-production/releases`, with `/opt/cnt-production/current` pointing to the active release. `/etc/cnt-production.env` contains the runtime API token and must remain mode `0600`.

The GitHub Pages build uses hash routing and the public HTTPS API URL. API requests require a runtime Bearer token and an `X-CNT-Workspace` header generated in the browser.
