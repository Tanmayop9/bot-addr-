"""
add_bots.py – Add all bots owned by a Discord user to a target guild.

Usage:
    python add_bots.py

The script will prompt you for your Discord token and the target guild ID,
then add every bot you own to that guild with permissions=8 (Administrator).
No secrets are stored anywhere.
"""

import sys

import requests

# ── Constants ──────────────────────────────────────────────────────────────────

PERMISSIONS = 8   # Administrator
BASE_URL = "https://discord.com/api/v10"

# ── Helpers ────────────────────────────────────────────────────────────────────


def _safe_json(response: requests.Response) -> dict | list:
    """Return parsed JSON, or a dict with an error message on failure."""
    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        return {"message": response.text or f"HTTP {response.status_code}"}
    try:
        return response.json()
    except ValueError:
        return {"message": response.text or f"HTTP {response.status_code}"}


def get_headers(token: str) -> dict:
    return {
        "Authorization": token,
        "Content-Type": "application/json",
    }


def fetch_owned_applications(token: str) -> list[dict]:
    """Return a list of application objects owned by the authenticated user."""
    url = f"{BASE_URL}/applications"
    params = {"with_team_applications": "false"}
    response = requests.get(url, headers=get_headers(token), params=params, timeout=10)

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

    response = requests.post(
        url,
        headers=get_headers(token),
        params=params,
        json=payload,
        timeout=10,
    )
    return {"status_code": response.status_code, "body": _safe_json(response)}


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    # ── Prompt for credentials (nothing stored) ────────────────────────────────
    import getpass
    token = getpass.getpass("Enter your Discord token: ").strip()
    if not token:
        print("[ERROR] Token cannot be empty.")
        sys.exit(1)

    guild_id = input("Enter the target guild ID [default: 293939939]: ").strip()
    if not guild_id:
        guild_id = "293939939"

    # ── Fetch and add bots ─────────────────────────────────────────────────────
    print("\n[INFO] Fetching applications owned by you …")
    apps = fetch_owned_applications(token)

    if not apps:
        print("[INFO] No owned applications found.")
        return

    print(f"[INFO] Found {len(apps)} application(s). Adding to guild {guild_id} "
          f"with permissions={PERMISSIONS} …\n")

    for app in apps:
        app_id = app.get("id", "unknown")
        app_name = app.get("name", "unknown")

        result = authorize_bot(token, app_id, guild_id, PERMISSIONS)
        status = result["status_code"]
        body = result["body"]

        if status == 200:
            print(f"[OK]    {app_name} ({app_id}) → added successfully.")
        else:
            error_msg = body.get("message", body)
            print(f"[FAIL]  {app_name} ({app_id}) → HTTP {status}: {error_msg}")

    print("\n[INFO] Done.")


if __name__ == "__main__":
    main()
