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
import time

import pyotp
import requests

# ── Constants ──────────────────────────────────────────────────────────────────

PERMISSIONS = 8   # Administrator
BASE_URL = "https://discord.com/api/v10"
DISCORD_BASE_URL = "https://discord.com"
TOKEN_FILE = "tokens.txt"  # bot tokens are appended here after each reset
NOPECHA_API_URL = "https://api.nopecha.com"
NOPECHA_POLL_INTERVAL = 3    # seconds between each result poll
NOPECHA_MAX_POLLS = 40       # maximum polls before giving up (~2 minutes total)
NOPECHA_ERROR_NOT_READY = 9  # NopeCHA error code meaning the task is still processing

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


# ── CAPTCHA solver ─────────────────────────────────────────────────────────────


def solve_hcaptcha_manual(sitekey: str) -> str | None:
    """
    Guide the user to solve the hCaptcha challenge manually in a browser
    and paste the resulting token back — completely free, no signup needed.

    Parameters
    ----------
    sitekey : str
        The ``captcha_sitekey`` value returned by Discord in the 400 response.

    Returns
    -------
    str | None
        The hCaptcha response token pasted by the user, or ``None`` if skipped.
    """
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║              MANUAL CAPTCHA SOLVE  (free, no sign-up)           ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print("║  Discord requires a CAPTCHA. Follow these steps:                ║")
    print("║                                                                  ║")
    print("║  1. Open this URL in any browser (desktop or mobile):           ║")
    print(f"║     https://discord.com/developers/applications/new             ║")
    print("║                                                                  ║")
    print("║  2. Open Browser DevTools → Network tab (F12 on desktop).       ║")
    print("║                                                                  ║")
    print("║  3. Fill in any app name and click Create.                       ║")
    print("║     If a CAPTCHA appears, solve it.                              ║")
    print("║                                                                  ║")
    print("║  4. In the Network tab, find the request to:                     ║")
    print("║        POST /api/v10/applications                               ║")
    print("║     Open its Payload/Body. Copy the value of 'captcha_key'.     ║")
    print("║                                                                  ║")
    print("║  5. Paste it below and press Enter.                              ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"[INFO] Expected sitekey: {sitekey}")
    print()
    token = input("Paste hCaptcha token here (or press Enter to skip): ").strip()
    return token if token else None


def solve_hcaptcha_nopecha(nopecha_key: str, sitekey: str, rqdata: str) -> str | None:
    """
    Solve a Discord hCaptcha Enterprise challenge via NopeCHA
    (https://nopecha.com) — optional free-tier API, requires sign-up.

    Parameters
    ----------
    nopecha_key : str
        Your NopeCHA API key.
    sitekey : str
        The ``captcha_sitekey`` value returned by Discord in the 400 response.
    rqdata : str
        The ``captcha_rqdata`` value returned by Discord (Enterprise payload).

    Returns
    -------
    str | None
        The solved hCaptcha token, or ``None`` on failure.
    """
    task_payload = {
        "key": nopecha_key,
        "type": "hcaptcha",
        "sitekey": sitekey,
        "url": DISCORD_BASE_URL,
        "data": rqdata,
    }

    try:
        resp = requests.post(
            NOPECHA_API_URL,
            json=task_payload,
            timeout=15,
        )
        data = resp.json()
    except Exception as exc:
        print(f"[WARN]  NopeCHA task creation failed: {exc}")
        return None

    # NopeCHA returns {"error": 0, "data": "<task_id>"} on success.
    if data.get("error", 0) != 0:
        print(f"[WARN]  NopeCHA error {data.get('error')}: {data.get('message', 'unknown')}")
        return None

    task_id = data.get("data")
    if not task_id:
        print("[WARN]  NopeCHA returned no task ID.")
        return None

    print("[INFO] Waiting for CAPTCHA solution …")
    for _ in range(NOPECHA_MAX_POLLS):
        time.sleep(NOPECHA_POLL_INTERVAL)
        try:
            result_resp = requests.get(
                NOPECHA_API_URL,
                params={"id": task_id, "key": nopecha_key},
                timeout=15,
            )
            result = result_resp.json()
        except Exception as exc:
            print(f"[WARN]  NopeCHA poll failed: {exc}")
            continue

        error_code = result.get("error", 0)
        if error_code == NOPECHA_ERROR_NOT_READY:
            continue
        if error_code != 0:
            print(f"[WARN]  NopeCHA task failed (error {error_code}): {result.get('message', 'unknown')}")
            return None

        token = result.get("data")
        if token:
            return token
        print("[WARN]  NopeCHA solution missing token data.")
        return None

    print("[WARN]  NopeCHA CAPTCHA solving timed out.")
    return None


# ── Bot creator helpers ────────────────────────────────────────────────────────


def create_application(token: str, name: str, nopecha_key: str | None = None) -> dict:
    """Create a new Discord application (and its bot user) with the given name.

    If Discord returns a CAPTCHA challenge (HTTP 400 with
    ``captcha_key: ['captcha-required']``), the CAPTCHA is resolved via one
    of two methods:

    * **Automatic** (optional) – if *nopecha_key* is provided the challenge is
      solved via NopeCHA (https://nopecha.com) without any user interaction.
    * **Manual** (default, no signup needed) – the user is guided step-by-step
      to solve the challenge in a browser and paste the resulting token back.
    """
    url = f"{BASE_URL}/applications"
    payload = {"name": name}
    response = requests.post(url, headers=get_headers(token), json=payload, timeout=10)

    if response.status_code == 401:
        print("[ERROR] Invalid or expired Discord token.")
        sys.exit(1)

    body = _safe_json(response)

    # ── CAPTCHA challenge ──────────────────────────────────────────────────────
    if (
        response.status_code == 400
        and isinstance(body, dict)
        and "captcha-required" in body.get("captcha_key", [])
    ):
        print("[INFO] Discord requires a CAPTCHA to create the application.")

        sitekey = body.get("captcha_sitekey", "")
        rqdata = body.get("captcha_rqdata", "")
        rqtoken = body.get("captcha_rqtoken", "")

        if nopecha_key is not None:
            print("[INFO] Solving CAPTCHA automatically via NopeCHA …")
            captcha_token = solve_hcaptcha_nopecha(nopecha_key, sitekey, rqdata)
            if not captcha_token:
                print("[WARN]  NopeCHA failed. Falling back to manual solving …")
                captcha_token = solve_hcaptcha_manual(sitekey)
        else:
            captcha_token = solve_hcaptcha_manual(sitekey)

        if not captcha_token:
            print("[ERROR] No CAPTCHA token provided. Cannot create application.")
            sys.exit(1)

        print("[OK]    CAPTCHA token received. Retrying application creation …")
        payload["captcha_key"] = captcha_token
        payload["captcha_rqtoken"] = rqtoken
        response = requests.post(url, headers=get_headers(token), json=payload, timeout=10)
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

    # ── NopeCHA API key (optional automatic CAPTCHA solver) ───────────────────
    print("\n[INFO] Discord may require a CAPTCHA when creating new applications.")
    print("       Two modes are available:")
    print("         AUTOMATIC – provide a NopeCHA API key (free at https://nopecha.com).")
    print("         MANUAL    – press Enter; if a CAPTCHA appears you will be guided")
    print("                     through solving it in your browser and pasting the token.")
    nopecha_key_input = input("Enter NopeCHA API key (or press Enter for manual mode): ").strip()
    nopecha_key = nopecha_key_input if nopecha_key_input else None

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
        app = create_application(token, bot_name, nopecha_key)
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
