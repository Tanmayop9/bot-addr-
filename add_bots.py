"""
add_bots.py – Discord bot utility (Termux-friendly, no browser required).

Features:
  1. Add all bots owned by a Discord user to a target guild.
  2. Create a new bot application, enable all three privileged intents,
     reset its token (using an MFA/auth key), and invite it to a guild.

Usage:
    python add_bots.py

Bot tokens retrieved during a session are appended to ``tokens.txt`` in the
working directory so you never lose them.  All other credentials (Discord user
token, MFA code) are kept only in memory for the duration of the script.
"""

import sys

import pyotp
import requests

# ── Constants ──────────────────────────────────────────────────────────────────

PERMISSIONS = 8   # Administrator
BASE_URL = "https://discord.com/api/v10"
TOKEN_FILE = "tokens.txt"  # bot tokens are appended here after each reset

# Privileged intent flag bits (Discord Gateway Intent flags)
INTENT_PRESENCE        = 1 << 12   # 4096   – Presence Update intent
INTENT_GUILD_MEMBERS   = 1 << 13   # 8192   – Server Members intent
INTENT_MESSAGE_CONTENT = 1 << 15   # 32768  – Message Content intent
ALL_PRIVILEGED_INTENTS = INTENT_PRESENCE | INTENT_GUILD_MEMBERS | INTENT_MESSAGE_CONTENT

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


def get_headers(token: str, mfa_code: str = "") -> dict:
    """Build request headers; include MFA header when a code is provided."""
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }
    if mfa_code:
        headers["X-Discord-MFA-Authorization"] = mfa_code
    return headers


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


def save_token(bot_name: str, bot_id: str, bot_token: str) -> None:
    """Append *bot_token* to TOKEN_FILE so it is never lost between sessions."""
    line = f"{bot_name} ({bot_id}): {bot_token}\n"
    with open(TOKEN_FILE, "a", encoding="utf-8") as fh:
        fh.write(line)
    print(f"[OK]    Token saved to {TOKEN_FILE}")


def totp_code_from_key(secret_key: str) -> str:
    """
    Derive the current 6-digit TOTP code from a base-32 secret key
    (e.g. ``354n6cs4ptulgduoimkczgz72uv2wh3w``).

    The key is case-insensitive and may include spaces/dashes — they are
    stripped before use.
    """
    cleaned = secret_key.upper().replace(" ", "").replace("-", "")
    totp = pyotp.TOTP(cleaned)
    return totp.now()


# ── Bot creator helpers ────────────────────────────────────────────────────────


def create_application(token: str, name: str) -> dict:
    """Create a new Discord application (and its bot user) with the given name."""
    url = f"{BASE_URL}/applications"
    payload = {"name": name}
    response = requests.post(url, headers=get_headers(token), json=payload, timeout=10)

    if response.status_code == 401:
        print("[ERROR] Invalid or expired Discord token.")
        sys.exit(1)

    body = _safe_json(response)
    if response.status_code not in (200, 201):
        msg = body.get("message", body) if isinstance(body, dict) else body
        print(f"[ERROR] Could not create application: HTTP {response.status_code}: {msg}")
        sys.exit(1)

    return body


def enable_all_intents(token: str, app_id: str) -> None:
    """
    Enable all three privileged gateway intents on the bot:
      • Presence Update intent   (bit 12)
      • Server Members intent    (bit 13)
      • Message Content intent   (bit 15)
    """
    url = f"{BASE_URL}/applications/{app_id}/bot"
    payload = {"flags": ALL_PRIVILEGED_INTENTS}
    response = requests.patch(url, headers=get_headers(token), json=payload, timeout=10)

    body = _safe_json(response)
    if response.status_code not in (200, 204):
        msg = body.get("message", body) if isinstance(body, dict) else body
        print(f"[WARN]  Could not enable intents: HTTP {response.status_code}: {msg}")
    else:
        print("[OK]    All three privileged intents enabled.")


def reset_bot_token(token: str, app_id: str, mfa_code: str) -> str | None:
    """
    Reset (regenerate) the bot token for *app_id*.

    Discord requires an MFA TOTP code (or backup code) passed via the
    X-Discord-MFA-Authorization header.  Returns the new token string,
    or None on failure.
    """
    url = f"{BASE_URL}/applications/{app_id}/bot/reset"
    response = requests.post(
        url,
        headers=get_headers(token, mfa_code=mfa_code),
        json={},
        timeout=10,
    )

    body = _safe_json(response)
    if response.status_code == 200 and isinstance(body, dict) and "token" in body:
        return body["token"]

    msg = body.get("message", body) if isinstance(body, dict) else body
    print(f"[WARN]  Token reset failed: HTTP {response.status_code}: {msg}")
    return None


def build_invite_url(client_id: str, permissions: int = PERMISSIONS) -> str:
    """Return a Discord OAuth2 bot invite URL (no browser needed – copy & paste)."""
    return (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={client_id}&scope=bot&permissions={permissions}"
    )


# ── Flows ──────────────────────────────────────────────────────────────────────


def flow_add_bots(token: str) -> None:
    """Add every owned bot to a target guild."""
    guild_id = input("Enter the target guild ID [default: 293939939]: ").strip()
    if not guild_id:
        guild_id = "293939939"

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


def flow_create_bot(token: str) -> None:
    """
    Interactive bot-creator flow (Termux-friendly – no browser / no CAPTCHA):

    Prompts for a base name, the number of bots to create, an optional TOTP
    secret key (6-digit code auto-generated), and an optional target guild.
    Each bot is created in sequence; all retrieved tokens are saved to
    tokens.txt.
    """
    print("\n── Create new Discord bot(s) ─────────────────────────────────────────")

    # ── How many bots? ─────────────────────────────────────────────────────────
    count_raw = input("Enter the number of bots you wanna create [default: 1]: ").strip()
    if not count_raw:
        count = 1
    else:
        try:
            count = int(count_raw)
            if count < 1:
                raise ValueError
        except ValueError:
            print("[ERROR] Please enter a positive integer.")
            return

    # ── Base name ──────────────────────────────────────────────────────────────
    base_name = input("Enter a base name for the bot(s): ").strip()
    if not base_name:
        print("[ERROR] Bot name cannot be empty.")
        return

    # ── TOTP secret key (asked once, reused for every reset) ───────────────────
    print("\n[INFO] To reset/retrieve bot tokens, Discord requires an MFA code.")
    print("       Paste your TOTP secret key (e.g. 354n6cs4ptulgduoimkczgz72uv2wh3w).")
    print("       The current 6-digit code will be generated automatically for each bot.")
    print("       Press Enter to skip token reset for all bots.")
    totp_key = input("Enter TOTP secret key (or press Enter to skip): ").strip()

    # ── Optional guild ─────────────────────────────────────────────────────────
    add_to_guild = input("\nAdd each bot to a guild after creation? [y/N]: ").strip().lower()
    guild_id = ""
    if add_to_guild == "y":
        guild_id = input("Enter the target guild ID [default: 293939939]: ").strip()
        if not guild_id:
            guild_id = "293939939"

    # ── Loop ───────────────────────────────────────────────────────────────────
    print(f"\n[INFO] Creating {count} bot(s) …\n")

    for i in range(1, count + 1):
        # Every bot gets the exact same name the user entered
        bot_name = base_name
        print(f"──── Bot {i}/{count}: {bot_name} {'─' * max(0, 50 - len(bot_name))}")

        # Step 1 – Create the application
        print(f"[INFO] Creating application …")
        app = create_application(token, bot_name)
        app_id = app.get("id", "")
        app_name = app.get("name", bot_name)
        print(f"[OK]    Created: {app_name} (ID: {app_id})")

        # Step 2 – Enable all three privileged intents
        print("[INFO] Enabling all three privileged gateway intents …")
        enable_all_intents(token, app_id)

        # Step 3 – Reset token using a freshly generated TOTP code
        if totp_key:
            try:
                mfa_code = totp_code_from_key(totp_key)
            except Exception as exc:
                print(f"[ERROR] Could not generate TOTP code: {exc}")
                print("[INFO]  Skipped token reset for this bot.")
            else:
                print(f"[INFO] Generated MFA code: {mfa_code}")
                print("[INFO] Resetting bot token …")
                new_token = reset_bot_token(token, app_id, mfa_code)
                if new_token:
                    print(f"[OK]    Bot token: {new_token}")
                    print("[WARN]  Keep this token secret — treat it like a password!")
                    save_token(app_name, app_id, new_token)
                else:
                    print("[INFO]  Token not retrieved. Reset it later in the Developer Portal.")
        else:
            print("[INFO]  Skipped token reset.")

        # Step 4 – Invite URL
        invite_url = build_invite_url(app_id)
        print(f"[INFO] Invite URL: {invite_url}")

        # Step 5 – Optional auto-add to guild
        if guild_id:
            result = authorize_bot(token, app_id, guild_id, PERMISSIONS)
            status = result["status_code"]
            body = result["body"]
            if status == 200:
                print(f"[OK]    Added to guild {guild_id}.")
            else:
                error_msg = body.get("message", body) if isinstance(body, dict) else body
                print(f"[FAIL]  Could not add to guild: HTTP {status}: {error_msg}")

        print()  # blank line between bots

    print(f"[INFO] Done — {count} bot(s) processed.")
    if totp_key:
        print(f"[INFO] All retrieved tokens saved to {TOKEN_FILE}.")


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    import getpass

    # ── Prompt for credentials (nothing stored) ────────────────────────────────
    token = getpass.getpass("Enter your Discord token: ").strip()
    if not token:
        print("[ERROR] Token cannot be empty.")
        sys.exit(1)

    # ── Menu ───────────────────────────────────────────────────────────────────
    print("\nWhat would you like to do?")
    print("  [1] Add all owned bots to a guild")
    print("  [2] Create a new bot (enable intents + reset token + invite)")
    choice = input("Enter choice [1/2, default: 1]: ").strip()

    if choice == "2":
        flow_create_bot(token)
    else:
        flow_add_bots(token)


if __name__ == "__main__":
    main()
