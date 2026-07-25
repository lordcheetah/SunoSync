"""SunoSync Token Server — local bridge for the browser extension.

Listens on 127.0.0.1:38945 for token pushes from the SunoSync browser
extension.

Security model
--------------
The previous implementation answered every request with
``Access-Control-Allow-Origin: *`` and approved ``Content-Type`` in its CORS
preflight. That combination meant *any website you visited* while SunoSync was
running could POST to http://127.0.0.1:38945/token and overwrite your stored
Suno session token, which is then used for every API call the app makes.

Two independent controls replace it:

1. **Origin allowlist.** Requests carrying an ``Origin`` header that is not a
   browser-extension origin (``chrome-extension://`` / ``moz-extension://``)
   are rejected outright, and CORS headers are echoed back only for those
   origins. This is what stops a hostile web page: the browser will not let
   page JavaScript forge an extension ``Origin``.

2. **Pairing secret.** Every request must carry ``X-SunoSync-Auth`` matching a
   random secret generated on first run and shown in the app's Settings screen.
   This is what stops *other* extensions installed in the same browser, which
   the origin check alone cannot distinguish.

Neither control defends against a hostile process running as the same OS user —
such a process can read the secret file directly. That is out of scope; an
attacker at that privilege level can read the token from config.json anyway.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from core.paths import get_bridge_file

logger = logging.getLogger(__name__)

TOKEN_SERVER_HOST = "127.0.0.1"
TOKEN_SERVER_PORT = 38945

AUTH_HEADER = "X-SunoSync-Auth"

# Browser-extension origin schemes. Page origins (https://…) never match.
_EXTENSION_ORIGIN_RE = re.compile(r"^(chrome-extension|moz-extension|safari-web-extension)://[a-z0-9\-._]+$", re.I)

# Reject absurd bodies before reading them into memory.
MAX_BODY_BYTES = 16 * 1024

# Suno/Clerk session tokens are JWTs. Validating the shape stops junk and
# obvious garbage from overwriting a working token.
_JWT_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$")


def load_or_create_secret() -> str:
    """Return the pairing secret, generating and persisting one on first run."""
    path = get_bridge_file()

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        secret = data.get("pairing_secret")
        if isinstance(secret, str) and len(secret) >= 16:
            return secret
    except (OSError, ValueError):
        pass

    secret = secrets.token_urlsafe(24)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"pairing_secret": secret}, f, indent=2)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        logger.info("Generated a new extension pairing secret at %s", path)
    except OSError:
        logger.exception("Could not persist pairing secret; using an in-memory one")

    return secret


def is_extension_origin(origin: str | None) -> bool:
    """True when `origin` is a browser-extension origin.

    A missing Origin header is allowed: non-browser clients such as curl and the
    test-suite do not send one, and they cannot be driven by a hostile web page.
    The pairing secret is what authenticates those.
    """
    if origin is None or origin == "" or origin.lower() == "null":
        return True
    return bool(_EXTENSION_ORIGIN_RE.match(origin.strip()))


def looks_like_jwt(token: str) -> bool:
    """Cheap structural check; does not verify the signature."""
    return bool(token) and len(token) <= 8192 and bool(_JWT_RE.match(token))


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Serve each request on its own thread so a slow callback cannot block."""

    daemon_threads = True
    allow_reuse_address = False  # Do not let another process steal the port.


class _TokenHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the token server."""

    server_version = "SunoSync"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        """Suppress default stderr logging; use our logger instead."""
        logger.debug("TokenServer: %s", format % args)

    # --- helpers -----------------------------------------------------------

    def _origin_ok(self) -> bool:
        return is_extension_origin(self.headers.get("Origin"))

    def _auth_ok(self) -> bool:
        provided = self.headers.get(AUTH_HEADER, "")
        expected = getattr(self.server, "pairing_secret", "")
        # Constant-time comparison to avoid leaking the secret via timing.
        return bool(expected) and secrets.compare_digest(provided, expected)

    def _send_cors_headers(self):
        """Echo CORS headers back only for extension origins."""
        origin = self.headers.get("Origin")
        if origin and _EXTENSION_ORIGIN_RE.match(origin.strip()):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", f"Content-Type, {AUTH_HEADER}")
            self.send_header("Access-Control-Max-Age", "600")

    def _send_json(self, code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _reject(self, code, message):
        """Reject without CORS headers so the browser cannot read the response."""
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _guard(self) -> bool:
        """Run origin + auth checks. Returns True when the request may proceed."""
        if not self._origin_ok():
            logger.warning(
                "Rejected token-bridge request from non-extension origin: %r",
                self.headers.get("Origin"),
            )
            self._reject(403, "Forbidden origin")
            return False
        if not self._auth_ok():
            logger.warning("Rejected token-bridge request with a bad pairing secret")
            self._reject(401, "Invalid or missing pairing secret")
            return False
        return True

    # --- routes ------------------------------------------------------------

    def do_OPTIONS(self):
        """CORS preflight. Answered only for extension origins."""
        if not self._origin_ok():
            self._reject(403, "Forbidden origin")
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        """GET /status — health check, requires pairing."""
        if self.path != "/status":
            self._reject(404, "Not found")
            return
        if not self._guard():
            return
        self._send_json(200, {"running": True, "app": "SunoSync"})

    def do_POST(self):
        """POST /token — receive a session token from the extension."""
        if self.path != "/token":
            self._reject(404, "Not found")
            return
        if not self._guard():
            return

        try:
            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._send_json(400, {"error": "Invalid Content-Length"})
                return

            if content_length <= 0:
                self._send_json(400, {"error": "Empty body"})
                return
            if content_length > MAX_BODY_BYTES:
                self._send_json(413, {"error": "Body too large"})
                return

            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict):
                self._send_json(400, {"error": "Expected a JSON object"})
                return

            token = str(data.get("token", "")).strip()

            if not token:
                self._send_json(400, {"error": "No token provided"})
                return

            if not looks_like_jwt(token):
                logger.warning("Rejected a token that is not shaped like a JWT")
                self._send_json(400, {"error": "Token is not a well-formed JWT"})
                return

            server = self.server
            token_changed = False
            with server.token_lock:
                if server.current_token != token:
                    server.current_token = token
                    token_changed = True
                callbacks = list(server.token_callbacks)

            # Fire callbacks outside the lock to avoid deadlocks.
            if token_changed:
                for callback in callbacks:
                    try:
                        callback(token)
                    except Exception:
                        logger.exception("Token callback error")

                logger.info("Token received from extension (%d chars) [NEW]", len(token))
            else:
                logger.debug("Token received (unchanged)")

            self._send_json(200, {"success": True})

        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
        except Exception:
            logger.exception("Token server error")
            # Do not echo the exception text back to the caller.
            self._send_json(500, {"error": "Internal error"})


class TokenServer:
    """Local HTTP server that receives Suno session tokens from the extension.

    Usage::

        server = TokenServer()
        server.on_token(lambda token: print("Got token"))
        server.start()
        print("Pair the extension with:", server.pairing_secret)
        ...
        server.stop()
    """

    def __init__(self, host=TOKEN_SERVER_HOST, port=TOKEN_SERVER_PORT, pairing_secret=None):
        self.host = host
        self.port = port
        self.pairing_secret = pairing_secret or load_or_create_secret()
        self._httpd = None
        self._thread = None
        self._running = False
        self._pending_callbacks = []

    def stop(self):
        """Stop the token server and release the port."""
        if not self._httpd:
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            logger.exception("Error shutting down token server")
        finally:
            self._httpd = None
            self._running = False
            logger.info("Token server stopped")

    def on_token(self, callback):
        """Register a callback invoked with the token string on each new token."""
        if self._httpd:
            self._httpd.token_callbacks.append(callback)
        else:
            self._pending_callbacks.append(callback)

    def _flush_pending_callbacks(self):
        if self._httpd:
            self._httpd.token_callbacks.extend(self._pending_callbacks)
            self._pending_callbacks.clear()

    def start(self):
        """Start the token server on a background thread."""
        if self._running:
            logger.warning("Token server is already running")
            return

        # Refuse to bind anywhere but loopback, whatever the caller passed in.
        if self.host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError(f"Token server may only bind to loopback, got {self.host!r}")

        try:
            self._httpd = _ThreadingHTTPServer((self.host, self.port), _TokenHandler)
            self._httpd.token_lock = threading.Lock()
            self._httpd.current_token = None
            self._httpd.token_callbacks = []
            self._httpd.pairing_secret = self.pairing_secret

            self._flush_pending_callbacks()

            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                daemon=True,
                name="SunoSync-TokenServer",
            )
            self._thread.start()
            self._running = True
            logger.info("Token server started on %s:%d", self.host, self.port)
        except OSError as e:
            self._httpd = None
            if "address already in use" in str(e).lower() or "10048" in str(e):
                logger.warning(
                    "Token server port %d already in use — is SunoSync already running?",
                    self.port,
                )
            else:
                logger.error("Failed to start token server: %s", e)

    @property
    def is_running(self):
        return self._running

    @property
    def current_token(self):
        """Get the last received token (thread-safe)."""
        if self._httpd:
            with self._httpd.token_lock:
                return self._httpd.current_token
        return None
