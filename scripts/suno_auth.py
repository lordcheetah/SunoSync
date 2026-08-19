#!/usr/bin/env python3
"""Store the Suno client cookie so long runs can mint their own tokens.

Session tokens last one hour. Keeping them fresh normally means keeping a
browser and the SunoSync extension alive, which does not survive an overnight
archive in Firefox or Zen -- temporary add-ons get unloaded and the token stops
being refreshed.

The ``__client`` cookie is the longer-lived credential the browser itself uses
to mint those tokens. Stored once in Windows Credential Manager, the archiver
can mint its own and needs no browser at all.

    # Easiest: read it straight out of your browser profile.
    python scripts/suno_auth.py import

    # Or paste it yourself (prompts without echoing):
    python scripts/suno_auth.py set

    # Check it still works:
    python scripts/suno_auth.py test

    # Remove it:
    python scripts/suno_auth.py clear

``import`` handles this for you by reading the cookie out of Zen, Firefox,
LibreWolf or Waterfox. To do it by hand instead: open suno.com while signed in,
press Shift+F9 for the Storage inspector, and copy ``__client`` under
**https://auth.suno.com** -- note it is scoped to auth.suno.com, not suno.com.

Treat the cookie like a password: it can mint session tokens until it expires
or you sign out.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser_cookies import (  # noqa: E402
    BrowserCookieError,
    find_profiles,
    read_client_cookie,
)
from core.clerk import ClerkAuthError, mint_session_token, session_id_from_token  # noqa: E402
from core.config_manager import ConfigManager  # noqa: E402
from core.secrets import (  # noqa: E402
    COOKIE_ENV_VAR,
    clear_client_cookie,
    get_client_cookie,
    keyring_available,
    set_client_cookie,
)

log = logging.getLogger("suno-auth")


def _known_token():
    """Any previous token, used only to read its session id."""
    return (ConfigManager("config.json").get("token") or "").strip() or None


def _describe(token):
    from core.archiver import token_seconds_left

    left = token_seconds_left(token)
    if left is None:
        return "lifetime unknown"
    return f"valid for {left / 60:.0f} more minutes"


def cmd_set(_args):
    if not keyring_available():
        log.error(
            "No OS keystore is available, so the cookie cannot be stored securely.\n"
            "Install it with:  pip install keyring\n"
            "Or supply the cookie per-run without storing it:  set %s=<value>",
            COOKIE_ENV_VAR,
        )
        return 2

    print(
        "Open suno.com while signed in, press Shift+F9 for the Storage inspector,\n"
        "and copy the __client value under https://auth.suno.com.\n"
        "(Or let 'import' read it from your browser profile automatically.)\n"
    )
    cookie = getpass.getpass("Paste the __client cookie (input hidden): ").strip()
    if not cookie:
        log.error("Nothing entered.")
        return 2
    if cookie.startswith("__client="):
        cookie = cookie.split("=", 1)[1].strip()

    print("\nChecking it with Clerk before storing...")
    try:
        token = mint_session_token(cookie, known_token=_known_token())
    except ClerkAuthError as exc:
        log.error("%s", exc)
        log.error("Nothing was stored.")
        return 1

    if not set_client_cookie(cookie):
        return 1

    print(f"Stored in Windows Credential Manager. Minted a token: {_describe(token)}.")
    print("Long runs will now mint their own tokens and need no browser.")
    return 0


def cmd_import(_args):
    profiles = find_profiles()
    if not profiles:
        log.error("No Firefox-family browser profile found. Use 'set' to paste it instead.")
        return 2

    print(f"Found {len(profiles)} profile(s); trying most recently used first.\n")
    known = _known_token()

    for browser, name, path in profiles:
        try:
            cookie = read_client_cookie(path)
        except BrowserCookieError as exc:
            print(f"  {browser:10s} {name[:28]:30s} unreadable ({exc})")
            continue
        if not cookie:
            print(f"  {browser:10s} {name[:28]:30s} no {'__client'} cookie")
            continue

        print(f"  {browser:10s} {name[:28]:30s} found ({len(cookie)} chars) - validating...")
        try:
            token = mint_session_token(cookie, known_token=known)
        except ClerkAuthError as exc:
            print(f"      rejected: {exc}")
            continue

        if not set_client_cookie(cookie):
            return 1
        print(f"\nStored from {browser}. Minted a token: {_describe(token)}.")
        print("Long runs will now mint their own tokens and need no browser.")
        return 0

    log.error("No usable cookie found. Sign in to suno.com, then try again.")
    return 1


def cmd_test(_args):
    cookie = get_client_cookie()
    if not cookie:
        log.error("No cookie stored. Run:  python scripts/suno_auth.py set")
        return 2

    source = "environment" if os.environ.get(COOKIE_ENV_VAR) else "keystore"
    print(f"Cookie found in the {source}.")
    try:
        token = mint_session_token(cookie, known_token=_known_token())
    except ClerkAuthError as exc:
        log.error("%s", exc)
        return 1

    print(f"Minted a session token: {_describe(token)}.")
    print(f"Clerk session: {session_id_from_token(token)}")
    return 0


def cmd_clear(_args):
    print("Cleared." if clear_client_cookie() else "Nothing was stored.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("set", help="Store the __client cookie (validated first).").set_defaults(fn=cmd_set)
    sub.add_parser(
        "import", help="Read the cookie from Zen/Firefox and store it."
    ).set_defaults(fn=cmd_import)
    sub.add_parser("test", help="Mint a token to confirm the cookie works.").set_defaults(fn=cmd_test)
    sub.add_parser("clear", help="Remove the stored cookie.").set_defaults(fn=cmd_clear)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not getattr(args, "fn", None):
        parser.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
