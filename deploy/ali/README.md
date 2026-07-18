# Ali backend deployment

The production API runs on loopback port `8768` and is exposed through Caddy at:

`https://cnt-analysis.47.236.76.214.nip.io`

Persistent state lives under `/opt/cnt-production/data`; releases are immutable directories under `/opt/cnt-production/releases`, with `/opt/cnt-production/current` pointing to the active release. `/etc/cnt-production.env` contains runtime configuration and must remain mode `0600`.

Production account authentication requires these runtime values:

- `CNT_AUTH_USERS_B64`: URL-safe Base64 JSON array containing `username`, `display_name`, and a PBKDF2 `password_hash` for every user.
- `CNT_AUTH_SECRET`: random session-signing secret of at least 32 bytes.
- `CNT_AUTH_TOKEN_TTL_SECONDS`: signed-session lifetime; production currently uses 12 hours (`43200`).
- `CNT_ALLOWED_ORIGINS`: exact GitHub Pages origin (`https://zuestian.github.io`).

Never store plaintext passwords, password hashes, or the signing secret in Git. If either account setting is missing, the service fails closed at startup rather than silently exposing the API. `CNT_API_TOKEN` remains a legacy fallback only when account authentication is not configured.

The GitHub Pages build uses hash routing, the public HTTPS API URL, and `VITE_REQUIRE_LOGIN=true`. The browser stores only the signed session and a random `X-CNT-Workspace` identifier. `/api/v1/health` and `/api/v1/auth/login` are public; every other v1 route requires a valid session.
