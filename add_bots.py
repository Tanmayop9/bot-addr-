"""
add_bots.py – Discord bot adder utility (Termux-friendly, no browser required).

Adds all bots owned by a Discord user to a target guild.
Bots that are already in the guild are skipped to avoid rate limiting.

Usage:
    python add_bots.py
"""

import base64
import json as _json
import sys

import requests

# Optional: curl_cffi impersonates Chrome's TLS fingerprint so Discord does not
# trigger a CAPTCHA challenge — works on Termux without any browser or sign-up.
# Install once with:  pip install curl_cffi
try:
    from curl_cffi import requests as _cffi_requests
    _CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CFFI_AVAILABLE = False

# ── Constants ──────────────────────────────────────────────────────────────────

PERMISSIONS = 8   # Administrator
BASE_URL = "https://discord.com/api/v10"
DEFAULT_GUILD = "1479676935683575960"

# curl_cffi impersonation target — matches Chrome 120 on Android
_IMPERSONATE = "chrome120"

# Browser-like identity appended to every Discord API request.
# Presenting a realistic Chrome/Android fingerprint makes Discord much less
# likely to issue a CAPTCHA — no browser or external service needed.
_DISCORD_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; K) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
_DISCORD_SUPER_PROPERTIES = base64.b64encode(
    _json.dumps(
        {
            "os": "Android",
            "browser": "Chrome",
            "device": "Android",
            "system_locale": "en-US",
            "browser_user_agent": _DISCORD_USER_AGENT,
            "browser_version": "120.0.0.0",
            "os_version": "10",
            "release_channel": "stable",
            "client_build_number": 280369,
            "client_event_source": None,
        },
        separators=(",", ":"),
    ).encode()
).decode()

# ── HTTP helpers (curl_cffi when available, requests otherwise) ────────────────


def _get(url: str, **kwargs):
    """HTTP GET — uses curl_cffi Chrome impersonation when available."""
    if _CFFI_AVAILABLE:
        return _cffi_requests.get(url, impersonate=_IMPERSONATE, **kwargs)
    return requests.get(url, **kwargs)


def _post(url: str, **kwargs):
    """HTTP POST — uses curl_cffi Chrome impersonation when available."""
    if _CFFI_AVAILABLE:
        return _cffi_requests.post(url, impersonate=_IMPERSONATE, **kwargs)
    return requests.post(url, **kwargs)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _safe_json(response: "requests.Response | object") -> dict | list:
    """Return parsed JSON, or a dict with an error message on failure."""
    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        return {"message": response.text or f"HTTP {response.status_code}"}
    try:
        return response.json()
    except ValueError:
        return {"message": response.text or f"HTTP {response.status_code}"}


def get_headers(token: str) -> dict:
    """Build Discord API request headers."""
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": _DISCORD_USER_AGENT,
        "X-Super-Properties": _DISCORD_SUPER_PROPERTIES,
        "X-Discord-Locale": "en-US",
    }


def fetch_owned_applications(token: str) -> list[dict]:
    """Return a list of application objects owned by the authenticated user."""
    url = f"{BASE_URL}/applications"
    params = {"with_team_applications": "false"}
    response = _get(url, headers=get_headers(token), params=params, timeout=10)

    if response.status_code == 401:
        print("[ERROR] Invalid or expired Discord token.")
        sys.exit(1)

    response.raise_for_status()
    apps = _safe_json(response)

    if not isinstance(apps, list):
        print(f"[ERROR] Unexpected response from Discord API: {apps}")
        sys.exit(1)

    return apps


def authorize_bot(token: str, client_id: str, guild_id: str, permissions: int) -> dict:
    """
    Authorize a bot (client_id) into guild_id with the given permissions integer.

    This mirrors what the Discord browser client does when you click 'Authorise'
    on the OAuth2 consent screen:
        POST /oauth2/authorize?client_id=…&scope=bot&permissions=…
    """
    url = f"{BASE_URL}/oauth2/authorize"
    params = {
        "client_id": client_id,
        "scope": "bot",
        "permissions": str(permissions),
    }
    payload = {
        "authorize": True,
        "guild_id": guild_id,
        "permissions": str(permissions),
    }

    response = _post(
        url,
        headers=get_headers(token),
        params=params,
        json=payload,
        timeout=10,
    )
    return {"status_code": response.status_code, "body": _safe_json(response)}


def fetch_guild_bot_ids(token: str, guild_id: str) -> set[str]:
    """Return a set of bot user IDs already present in the guild.

    Iterates through all guild members (paginated, up to 1 000 per page) and
    collects the IDs of members that are bots.  Returns an empty set when the
    guild is not accessible with the provided token so the caller can still
    proceed without the skip optimisation.
    """
    bot_ids: set[str] = set()
    after = "0"
    while True:
        url = f"{BASE_URL}/guilds/{guild_id}/members"
        params = {"limit": 1000, "after": after}
        response = _get(url, headers=get_headers(token), params=params, timeout=10)
        if response.status_code != 200:
            if response.status_code in (401, 403):
                print("[WARN]  Cannot read guild members — already-added check skipped.")
            break
        members = _safe_json(response)
        if not isinstance(members, list) or not members:
            break
        for member in members:
            user = member.get("user", {})
            if user.get("bot"):
                bot_ids.add(user["id"])
        if len(members) < 1000:
            break
        after = members[-1]["user"]["id"]
    return bot_ids


# ── Flow ───────────────────────────────────────────────────────────────────────


def flow_add_bots(token: str) -> None:
    """Add every owned bot to a target guild, skipping bots already present.

    The three steps are performed in strict order:
      1. Fetch all bot client IDs owned by the user.
      2. Check which of those bots are already in the guild.
      3. Add only the bots that are not yet in the guild.
    """
    guild_id = input(
        f"Enter the target guild ID [default: {DEFAULT_GUILD}]: "
    ).strip()
    if not guild_id:
        guild_id = DEFAULT_GUILD

    # ── Step 1: Fetch all bot client IDs ─────────────────────────────────────
    print("\n[INFO] Step 1 — Fetching all bot client IDs owned by you …")
    apps = fetch_owned_applications(token)

    if not apps:
        print("[INFO] No owned applications found.")
        return

    # Build a mapping of client_id → app_name for easy lookup later.
    all_bots: dict[str, str] = {
        app["id"]: app.get("name", "unknown")
        for app in apps
        if app.get("id")
    }
    preview_ids = list(all_bots.keys())[:5]
    suffix = f" … (+{len(all_bots) - 5} more)" if len(all_bots) > 5 else ""
    print(f"[INFO] Found {len(all_bots)} bot client ID(s): {', '.join(preview_ids)}{suffix}")

    # ── Step 2: Check which bots are already in the guild ────────────────────
    print(f"\n[INFO] Step 2 — Checking which bots are already in guild {guild_id} …")
    existing_bot_ids = fetch_guild_bot_ids(token, guild_id)
    if existing_bot_ids:
        print(f"[INFO] {len(existing_bot_ids)} bot(s) already in guild — will be skipped.")

    bots_to_add = {
        client_id: name
        for client_id, name in all_bots.items()
        if client_id not in existing_bot_ids
    }
    already_in_guild = {
        client_id: name
        for client_id, name in all_bots.items()
        if client_id in existing_bot_ids
    }

    for client_id, name in already_in_guild.items():
        print(f"[SKIP]  {name} ({client_id}) → already in guild.")

    if not bots_to_add:
        print("\n[INFO] All bots are already in the guild. Nothing to add.")
        return

    # ── Step 3: Add bots that are not yet in the guild ───────────────────────
    print(
        f"\n[INFO] Step 3 — Adding {len(bots_to_add)} bot(s) to guild {guild_id} "
        f"with permissions={PERMISSIONS} …\n"
    )

    for client_id, name in bots_to_add.items():
        result = authorize_bot(token, client_id, guild_id, PERMISSIONS)
        status = result["status_code"]
        body = result["body"]

        if status == 200:
            print(f"[OK]    {name} ({client_id}) → added successfully.")
        else:
            error_msg = body.get("message", body) if isinstance(body, dict) else body
            print(f"[FAIL]  {name} ({client_id}) → HTTP {status}: {error_msg}")

    print("\n[INFO] Done.")


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    import getpass

    if _CFFI_AVAILABLE:
        print("[INFO] curl_cffi active — Chrome TLS fingerprint (CAPTCHA bypass on).")
    else:
        print("[WARN] curl_cffi not installed. Discord may require a CAPTCHA.")
        print("       Fix: pip install curl_cffi")

    token = getpass.getpass("Enter your Discord token: ").strip()
    if not token:
        print("[ERROR] Token cannot be empty.")
        sys.exit(1)

    flow_add_bots(token)


if __name__ == "__main__":
    main()
