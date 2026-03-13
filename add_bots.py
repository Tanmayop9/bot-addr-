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

import base64
import json as _json
import sys
import time

import pyotp
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
DISCORD_BASE_URL = "https://discord.com"
TOKEN_FILE = "tokens.txt"  # bot tokens are appended here after each reset
NOPECHA_API_URL = "https://api.nopecha.com"
CAPTCHA_POLL_INTERVAL = 3    # seconds between each result poll
CAPTCHA_MAX_POLLS = 40       # maximum polls before giving up (~2 minutes total)

# Privileged intent flag bits (Discord Gateway Intent flags)
INTENT_PRESENCE        = 1 << 12   # 4096   – Presence Update intent
INTENT_GUILD_MEMBERS   = 1 << 13   # 8192   – Server Members intent
INTENT_MESSAGE_CONTENT = 1 << 15   # 32768  – Message Content intent
ALL_PRIVILEGED_INTENTS = INTENT_PRESENCE | INTENT_GUILD_MEMBERS | INTENT_MESSAGE_CONTENT

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


def _patch(url: str, **kwargs):
    """HTTP PATCH — uses curl_cffi Chrome impersonation when available."""
    if _CFFI_AVAILABLE:
        return _cffi_requests.patch(url, impersonate=_IMPERSONATE, **kwargs)
    return requests.patch(url, **kwargs)


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


def get_headers(token: str, mfa_code: str = "") -> dict:
    """Build request headers; include MFA header when a code is provided."""
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": _DISCORD_USER_AGENT,
        "X-Super-Properties": _DISCORD_SUPER_PROPERTIES,
        "X-Discord-Locale": "en-US",
    }
    if mfa_code:
        headers["X-Discord-MFA-Authorization"] = mfa_code
    return headers


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
    Guide the user to solve the hCaptcha challenge and paste the token back.
    Works on Android / Termux using Kiwi Browser (which has DevTools support).
    No sign-up, no API key, no PC needed.

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
    print("║          MANUAL CAPTCHA SOLVE — Android / Termux guide          ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print("║  TIP: install curl_cffi to skip this entirely next time:        ║")
    print("║        pip install curl_cffi                                     ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print("║  Right now, follow these steps on your Android device:          ║")
    print("║                                                                  ║")
    print("║  1. Install Kiwi Browser from the Play Store.                   ║")
    print("║     (It is the only Android browser with DevTools support.)     ║")
    print("║                                                                  ║")
    print("║  2. Open Kiwi and go to:                                        ║")
    print("║        https://discord.com/developers/applications/new          ║")
    print("║                                                                  ║")
    print("║  3. Tap the Kiwi menu (⋮) → 'Developer tools' → Network tab.   ║")
    print("║                                                                  ║")
    print("║  4. Type any app name, tap Create, then solve the CAPTCHA.      ║")
    print("║                                                                  ║")
    print("║  5. In the Network tab find POST /api/v10/applications.         ║")
    print("║     Tap it → Payload. Copy the 'captcha_key' value.             ║")
    print("║                                                                  ║")
    print("║  6. Paste it below and press Enter.                              ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"[INFO] Expected sitekey: {sitekey}")
    print()
    token = input("Paste hCaptcha token here (or press Enter to skip): ").strip()
    return token if token else None


def solve_hcaptcha_nopecha(nopecha_key: str, sitekey: str, rqdata: str = "", url: str = DISCORD_BASE_URL) -> str | None:
    """
    Solve a Discord hCaptcha challenge via NopeCHA
    (https://nopecha.com) — free tier available, no credit card required.

    Parameters
    ----------
    nopecha_key : str
        Your NopeCHA API key (register free at https://nopecha.com).
    sitekey : str
        The ``captcha_sitekey`` value returned by Discord in the 400 response.
    rqdata : str
        The ``captcha_rqdata`` value returned by Discord (Enterprise payload,
        may be empty for non-Enterprise challenges).
    url : str
        The page URL where the CAPTCHA is presented.

    Returns
    -------
    str | None
        The solved hCaptcha token, or ``None`` on failure.
    """
    task_payload: dict = {
        "key": nopecha_key,
        "type": "hcaptcha",
        "sitekey": sitekey,
        "url": url,
    }
    if rqdata:
        task_payload["data"] = rqdata

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

    if data.get("error"):
        print(f"[WARN]  NopeCHA error: {data.get('message', 'unknown')}")
        return None

    task_id = data.get("data")
    if not task_id:
        print("[WARN]  NopeCHA returned no task ID.")
        return None

    print("[INFO] Waiting for NopeCHA CAPTCHA solution …")
    for _ in range(CAPTCHA_MAX_POLLS):
        time.sleep(CAPTCHA_POLL_INTERVAL)
        try:
            result_resp = requests.get(
                NOPECHA_API_URL,
                params={"key": nopecha_key, "id": task_id},
                timeout=15,
            )
            result = result_resp.json()
        except Exception as exc:
            print(f"[WARN]  NopeCHA poll failed: {exc}")
            continue

        if result.get("error"):
            if result.get("message") == "incomplete":
                continue  # still processing
            print(f"[WARN]  NopeCHA task failed: {result.get('message', 'unknown')}")
            return None

        token = result.get("data")
        if token and isinstance(token, str):
            return token

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
      to solve the challenge in Kiwi Browser and paste the resulting token back.
    """
    url = f"{BASE_URL}/applications"
    payload = {"name": name}
    response = _post(url, headers=get_headers(token), json=payload, timeout=10)

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
        response = _post(url, headers=get_headers(token), json=payload, timeout=10)
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
    response = _patch(url, headers=get_headers(token), json=payload, timeout=10)

    body = _safe_json(response)
    if response.status_code not in (200, 204):
        msg = body.get("message", body) if isinstance(body, dict) else body
        print(f"[WARN]  Could not enable intents: HTTP {response.status_code}: {msg}")
    else:
        print("[OK]    All three privileged intents enabled.")


def _exchange_totp_for_mfa_token(user_token: str, totp_code: str, ticket: str) -> str | None:
    """
    Exchange a TOTP code and a Discord challenge *ticket* for an MFA
    authorization token.

    Discord uses a two-step MFA verification for sensitive operations such as
    bot token resets:

    1. The target endpoint is called (with or without the TOTP code in the
       ``X-Discord-MFA-Authorization`` header).  When Discord needs to issue a
       fresh MFA challenge it returns HTTP 401 with a short-lived ``ticket``
       string in the response body.
    2. That ticket, together with the current TOTP code, is posted here to
       ``POST /auth/mfa/totp``.  Discord validates the pair and returns a
       short-lived MFA authorization token.
    3. The MFA token is then used as the value of ``X-Discord-MFA-Authorization``
       in the original request.

    Returns the MFA token string on success, or ``None`` on failure.
    """
    url = f"{BASE_URL}/auth/mfa/totp"
    payload = {
        "code": totp_code,
        "ticket": ticket,
    }
    response = _post(
        url,
        headers=get_headers(user_token),
        json=payload,
        timeout=10,
    )
    body = _safe_json(response)
    if response.status_code == 200 and isinstance(body, dict) and "token" in body:
        return body["token"]
    msg = body.get("message", body) if isinstance(body, dict) else body
    print(f"[WARN]  MFA ticket exchange failed: HTTP {response.status_code}: {msg}")
    return None


def reset_bot_token(token: str, app_id: str, mfa_code: str) -> str | None:
    """
    Reset (regenerate) the bot token for *app_id*.

    Discord requires MFA authorization for this operation.  The function
    attempts two strategies in order:

    1. **Direct TOTP** – pass the 6-digit TOTP code straight in the
       ``X-Discord-MFA-Authorization`` header.  This works when Discord
       accepts the raw code without issuing a separate challenge.
    2. **Ticket flow** – if Discord responds with HTTP 401 and includes a
       challenge ``ticket`` in the response body, that ticket is exchanged
       for a short-lived MFA authorization token via
       ``POST /auth/mfa/totp``; the token is then used as the header value
       for a second attempt at the reset.

    Returns the new bot token string on success, or ``None`` on failure.
    """
    url = f"{BASE_URL}/applications/{app_id}/bot/reset"

    # Attempt 1: pass the TOTP code directly as the MFA header value.
    response = _post(
        url,
        headers=get_headers(token, mfa_code=mfa_code),
        json={},
        timeout=10,
    )
    body = _safe_json(response)

    # Attempt 2: if Discord issued a challenge ticket in the 401 response,
    # exchange (ticket + TOTP code) → MFA token and retry.
    if response.status_code == 401 and isinstance(body, dict):
        ticket = body.get("ticket")
        if ticket:
            mfa_auth_token = _exchange_totp_for_mfa_token(token, mfa_code, ticket)
            if mfa_auth_token:
                response = _post(
                    url,
                    headers=get_headers(token, mfa_code=mfa_auth_token),
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

    # ── NopeCHA API key (optional automatic CAPTCHA solver) ──────────────────
    print("\n[INFO] Discord may require a CAPTCHA when creating new applications.")
    if _CFFI_AVAILABLE:
        print("       curl_cffi is loaded — Chrome TLS fingerprint active.")
        print("       CAPTCHA is very unlikely. No key needed in most cases.")
    else:
        print("       curl_cffi is NOT installed. CAPTCHA is more likely.")
        print("       Strongly recommended: pip install curl_cffi")
    print("       Optional: provide a NopeCHA API key for automatic solving.")
    print("       (Free tier at https://nopecha.com — no credit card needed.)")
    print("       Otherwise press Enter — manual instructions will appear if needed.")
    nopecha_key_input = input("Enter NopeCHA API key (or press Enter to skip): ").strip()
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


# ── Flow 3: manage all owned bots ─────────────────────────────────────────────


def flow_manage_owned_bots(token: str) -> None:
    """
    Bulk-manage every bot you own in one pass:

    For each owned bot application:
      1. Enable all three privileged gateway intents.
      2. Reset the bot token using a TOTP MFA code.
      3. Add the bot to the target guild.
      4. Save the new token to ``tokens.txt``.
    """
    DEFAULT_GUILD = "1479676935683575960"

    print("\n── Manage all owned bots ─────────────────────────────────────────────")

    # ── TOTP secret key ────────────────────────────────────────────────────────
    print("\n[INFO] A TOTP MFA code is required to reset each bot token.")
    print("       Paste your TOTP secret key (e.g. 354n6cs4ptulgduoimkczgz72uv2wh3w).")
    print("       The current 6-digit code will be generated automatically for each bot.")
    totp_key = input("Enter TOTP secret key: ").strip()
    if not totp_key:
        print("[ERROR] TOTP key is required for token resets. Aborting.")
        return

    # ── Target guild ───────────────────────────────────────────────────────────
    guild_id = input(
        f"Enter the target guild ID [default: {DEFAULT_GUILD}]: "
    ).strip()
    if not guild_id:
        guild_id = DEFAULT_GUILD

    # ── Fetch all owned bots ───────────────────────────────────────────────────
    print("\n[INFO] Fetching all owned applications …")
    apps = fetch_owned_applications(token)

    if not apps:
        print("[INFO] No owned applications found.")
        return

    print(f"[INFO] Found {len(apps)} application(s). Processing …\n")

    for app in apps:
        app_id = app.get("id", "")
        app_name = app.get("name", "unknown")

        # 46 = target line width minus the fixed "──── " prefix and " (ID) " wrapper
        print(f"──── {app_name} ({app_id}) {'─' * max(0, 46 - len(app_name) - len(app_id))}")

        # Step 1 – Enable all three privileged intents
        print("[INFO] Enabling all three privileged gateway intents …")
        enable_all_intents(token, app_id)

        # Step 2 – Reset token using a fresh TOTP code
        try:
            mfa_code = totp_code_from_key(totp_key)
        except Exception as exc:
            print(f"[ERROR] Could not generate TOTP code: {exc}")
            print("[INFO]  Skipped — token not reset for this bot.")
            print()
            continue

        print(f"[INFO] Generated MFA code: {mfa_code}")
        print("[INFO] Resetting bot token …")
        new_token = reset_bot_token(token, app_id, mfa_code)

        if new_token:
            print(f"[OK]    Bot token: {new_token}")
            print("[WARN]  Keep this token secret — treat it like a password!")
            save_token(app_name, app_id, new_token)
        else:
            print("[WARN]  Token reset failed. Skipping token save for this bot.")

        # Step 3 – Add to guild
        print(f"[INFO] Adding to guild {guild_id} …")
        result = authorize_bot(token, app_id, guild_id, PERMISSIONS)
        status = result["status_code"]
        body = result["body"]
        if status == 200:
            print(f"[OK]    Added to guild {guild_id}.")
        else:
            error_msg = body.get("message", body) if isinstance(body, dict) else body
            print(f"[FAIL]  Could not add to guild: HTTP {status}: {error_msg}")

        print()  # blank line between bots

    print(f"[INFO] Done — {len(apps)} bot(s) processed.")
    print(f"[INFO] All retrieved tokens saved to {TOKEN_FILE}.")


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    import getpass

    # ── TLS bypass status ──────────────────────────────────────────────────────
    if _CFFI_AVAILABLE:
        print("[INFO] curl_cffi active — Chrome TLS fingerprint (CAPTCHA bypass on).")
    else:
        print("[WARN] curl_cffi not installed. Discord may require a CAPTCHA.")
        print("       Fix: pip install curl_cffi")

    # ── Prompt for credentials (nothing stored) ────────────────────────────────
    token = getpass.getpass("Enter your Discord token: ").strip()
    if not token:
        print("[ERROR] Token cannot be empty.")
        sys.exit(1)

    # ── Menu ───────────────────────────────────────────────────────────────────
    print("\nWhat would you like to do?")
    print("  [1] Add all owned bots to a guild")
    print("  [2] Create a new bot (enable intents + reset token + invite)")
    print("  [3] Manage all owned bots (enable intents + reset tokens + add to guild)")
    choice = input("Enter choice [1/2/3, default: 1]: ").strip()

    if choice == "2":
        flow_create_bot(token)
    elif choice == "3":
        flow_manage_owned_bots(token)
    else:
        flow_add_bots(token)


if __name__ == "__main__":
    main()
