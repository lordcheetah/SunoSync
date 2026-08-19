# Security

SunoSync handles your Suno session token, so it is worth being precise about
where that token lives, what can reach it, and what this fork changed.

> **Scope.** This policy covers
> [lordcheetah/SunoSync](https://github.com/lordcheetah/SunoSync), a fork of
> [sunsetsacoustic/SunoSync](https://github.com/sunsetsacoustic/SunoSync) by
> [@InternetThot](https://github.com/sunsetsacoustic). It is not affiliated with
> or endorsed by the original author.
>
> Several issues described below originate in the upstream code and may still be
> present there. They are documented here because this fork inherited and fixed
> them — not as criticism of the original project, which is the reason this app
> exists at all.

## Reporting a vulnerability

Report issues in **this fork** to this repository: open a
[GitHub issue](https://github.com/lordcheetah/SunoSync/issues) for anything
non-sensitive, or use GitHub's private
[security advisory](https://github.com/lordcheetah/SunoSync/security/advisories/new)
form for something exploitable.

If the issue also affects upstream, please report it to
[sunsetsacoustic/SunoSync](https://github.com/sunsetsacoustic/SunoSync/issues)
as well, so their users benefit too. Do not report bugs in *this fork's* builds
to the original author.

## What SunoSync stores, and where

Everything lives in your per-user application data directory
(`%LOCALAPPDATA%\InternetThot\SunoSync` on Windows):

| File | Contents |
| --- | --- |
| `config.json` | Settings **and your Suno session token**, in plain text |
| Windows Credential Manager | The Suno `__client` cookie, if stored (see below) |
| `token_bridge.json` | The pairing secret for the browser extension |
| `library_cache.json` | Scanned metadata about your local library |
| `tags.json` | Your Like/Star/Trash tags |
| `window_state.json` | Window geometry and last-seen version |
| `debug.log` | Rotating application log |

**The session token is stored unencrypted.** This is a deliberate trade-off, not
an oversight: OS keychain storage (Windows Credential Manager via `keyring`)
would protect it from other *users* on the machine, but not from any process
running as *you* — which is the realistic threat for a desktop app. What it
would add is protection against casual disclosure: cloud-synced folder backups,
screen shares, and support requests where someone zips up their config.

Migrating to `keyring` is a reasonable future change and is tracked as such. In
the meantime:

* the config file is written with owner-only permissions where the OS supports
  it, and
* **Settings → Browser Bridge → Sign out** clears the stored token.

Suno session tokens last exactly one hour (measured: the JWT's `exp` - `iat` is
3600), so a leaked token is less damaging than a leaked password but not
trivially so. The browser extension deliberately does **not** persist the token
to extension storage; it keeps only the expiry timestamp, so that a restarted
worker knows when to fetch a replacement.

## The client cookie

Session tokens are Clerk JWTs valid for exactly one hour. Keeping one fresh
normally means keeping a browser and the SunoSync extension running, which does
not survive an unattended overnight run: Firefox and Zen unload temporary
add-ons, and the archiver is then left holding an expired token.

`scripts/suno_auth.py import` reads the `__client` cookie out of your Zen,
Firefox, LibreWolf or Waterfox profile and stores it, so the archiver can mint
its own tokens directly:

    POST https://auth.suno.com/v1/client/sessions/{session_id}/tokens

**The cookie is a more powerful credential than the token it replaces.** The
token expires in an hour; the cookie can mint fresh tokens until it expires or
the session is signed out. It is therefore stored in the OS keystore -- Windows
Credential Manager, via `keyring` -- and never written to `config.json`, so it
does not end up in a folder backup or a cloud-synced directory alongside the
rest of the app's state.

The cookie is read from a copy of the browser's `cookies.sqlite`, taken because
a running browser holds a lock on the original. The copy is deleted immediately
afterwards, and the value is never logged. Note it is scoped to
`auth.suno.com` -- Suno's Clerk instance -- rather than to `suno.com`.

It is optional. Without it, the archiver falls back to whatever token the
extension last pushed, and long runs need the app and a suno.com tab kept
alive. To remove it: `python scripts/suno_auth.py clear`, or sign out of
suno.com, which invalidates it server-side.

`SUNOSYNC_CLIENT_COOKIE` overrides the keystore for a single run and persists
nothing.

## The local token bridge

When SunoSync is running it listens on `127.0.0.1:38945` so the browser
extension can hand over a fresh token.

### The vulnerability this replaced

The original implementation answered every request with
`Access-Control-Allow-Origin: *` and approved `Content-Type` in its CORS
preflight. Any website you visited while SunoSync was running could therefore
`POST http://127.0.0.1:38945/token` and overwrite your stored session token,
which the app then used for every API call. `GET /status` was also unauthenticated,
so any site could fingerprint whether you had SunoSync installed.

### The current design

Two independent controls, both of which must pass:

1. **Origin allowlist.** Requests whose `Origin` header is not a browser
   extension origin (`chrome-extension://`, `moz-extension://`,
   `safari-web-extension://`) are rejected with `403` and no CORS headers. A web
   page cannot forge an extension origin — the browser sets it.

2. **Pairing secret.** Every request must carry an `X-SunoSync-Auth` header
   matching a random secret generated on first run. Find it in
   **Settings → Browser Bridge** and paste it into the extension once. This is
   what stops *other* extensions in the same browser, which an origin check
   alone cannot distinguish. Comparison is constant-time.

Additionally: the listener refuses to bind to anything but loopback, request
bodies are capped at 16 KB, and tokens are rejected unless they are structurally
valid JWTs.

### What this does not defend against

A hostile process running as your OS user. It can read `token_bridge.json` and
`config.json` directly. Nothing at this layer can prevent that, and an attacker
with that access has already won.

## The browser extension

Two token-disclosure bugs were fixed alongside the bridge:

* `injected.js` posted the session JWT with `window.postMessage(..., '*')`,
  broadcasting it to every frame on the page including cross-origin iframes and
  any third-party script with a message listener. Messages are now addressed to
  the page's own origin.
* `content.js` relayed any message merely tagged `SUNOSYNC_TOKEN`, so any script
  on the page could inject a token of its choosing. Messages are now checked for
  source, origin, and a per-page-load channel id, and the token is validated as a
  JWT before being relayed.

The extension requests the narrowest permissions that work: `alarms`, `storage`,
and host access to `suno.com` plus the single loopback port.

## Crash reporting

Disabled by default. It activates only when a build is compiled with a
`SUNOSYNC_SENTRY_DSN` environment variable, and can be turned off in
**Settings → Privacy** or by setting `SUNOSYNC_DISABLE_SENTRY=1`.

When active, `services/crash_reporting.py` applies before anything leaves the
machine:

* `send_default_pii=False` and `include_local_variables=False` — stack frame
  locals routinely hold the session token;
* keys matching `token`, `authorization`, `cookie`, `session`, `secret`,
  `password`, `api_key`, `__client` and similar are replaced with `[redacted]`;
* JWT-shaped strings are redacted anywhere they appear, including inside free
  text and URLs;
* credentials in query strings are stripped;
* if scrubbing raises, the event is **dropped** rather than sent unredacted.

This is covered by tests in `tests/test_crash_reporting.py`.

## Update integrity

The updater previously fetched its manifest from a gist owned by the upstream
project and passed the `download_url` it found straight to `webbrowser.open()`.
Whoever controlled that gist could send every user to an arbitrary URL.

It now queries this repository's GitHub Releases API, and any URL is validated
as HTTPS on a known GitHub host before being opened — checked both in the
updater and again at the point of use. Releases are built by
`.github/workflows/release.yml` from a tag, and publish a `SHA256SUMS.txt`
alongside the binary.

Builds are **not** code-signed, so Windows SmartScreen and some antivirus
products will warn about them. Verify the SHA-256 checksum against the release
page if that matters to you, or build from source.
