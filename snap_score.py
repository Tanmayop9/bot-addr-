"""
snap_score.py – Snapchat score increaser utility (Termux-friendly).

Sends snaps on your behalf to increase your Snapchat score.
Uses the unofficial Snapchat web API with Chrome TLS fingerprinting
(via curl_cffi) to avoid detection.

Usage:
    python snap_score.py
"""

import sys
import time
import uuid

import requests

# Optional: curl_cffi impersonates Chrome's TLS fingerprint so Snapchat does
# not flag automated requests.  Install once with:  pip install curl_cffi
try:
    from curl_cffi import requests as _cffi_requests
    _CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CFFI_AVAILABLE = False

# ── Constants ──────────────────────────────────────────────────────────────────

SNAPCHAT_AUTH_URL = "https://auth.snapchat.com/login"
SNAPCHAT_STORIES_URL = "https://story.snapchat.com/add"
SNAPCHAT_SEND_URL = "https://app.snapchat.com/loq/send_message"
SNAPCHAT_UPLOAD_URL = "https://app.snapchat.com/loq/upload"

_IMPERSONATE = "chrome120"

# Realistic browser headers — reduces likelihood of bot detection.
_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; K) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

DEFAULT_SNAP_COUNT = 100
SEND_DELAY_SECONDS = 1.0   # pause between sends to avoid rate-limiting

# ── HTTP helpers ───────────────────────────────────────────────────────────────


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


def _safe_json(response) -> dict | list:
    """Return parsed JSON, or a dict with an error message on failure."""
    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        return {"message": response.text or f"HTTP {response.status_code}"}
    try:
        return response.json()
    except ValueError:
        return {"message": response.text or f"HTTP {response.status_code}"}


def _build_headers(auth_token: str) -> dict:
    """Build Snapchat API request headers."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "User-Agent": _USER_AGENT,
        "X-Snapchat-Client-Auth-Token": auth_token,
        "X-Request-ID": str(uuid.uuid4()),
        "Accept-Language": "en-US,en;q=0.9",
    }


# ── Core API calls ─────────────────────────────────────────────────────────────


def snapchat_login(username: str, password: str) -> str:
    """
    Authenticate with Snapchat and return the auth token.

    Raises SystemExit on failure so callers need not handle auth errors.
    """
    payload = {
        "username": username,
        "password": password,
        "grant_type": "password",
        "client_id": "android_client",
    }
    headers = {
        "User-Agent": _USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    response = _post(SNAPCHAT_AUTH_URL, data=payload, headers=headers, timeout=15)

    if response.status_code == 401:
        print("[ERROR] Invalid Snapchat username or password.")
        sys.exit(1)

    if response.status_code not in (200, 201):
        body = _safe_json(response)
        msg = body.get("message", body) if isinstance(body, dict) else body
        print(f"[ERROR] Login failed (HTTP {response.status_code}): {msg}")
        sys.exit(1)

    body = _safe_json(response)
    token = (
        body.get("access_token")
        or body.get("auth_token")
        or body.get("token")
    )
    if not token:
        print(f"[ERROR] Could not extract auth token from response: {body}")
        sys.exit(1)

    return str(token)


def send_snap(auth_token: str, recipient: str) -> dict:
    """
    Send a blank snap to *recipient* using the Snapchat loq API.

    Each sent snap increments the sender's Snapchat score by 1.
    Returns a dict with ``status_code`` and ``body`` keys.
    """
    media_id = str(uuid.uuid4()).upper()

    # Build a minimal snap payload — blank-image snap (1×1 transparent PNG).
    payload = {
        "media_id": media_id,
        "recipient_ids": [recipient],
        "type": "IMAGE",
        "capture_duration_secs": 3,
        "timer_duration_secs": 3,
        "story_metadata": {},
    }
    response = _post(
        SNAPCHAT_SEND_URL,
        json=payload,
        headers=_build_headers(auth_token),
        timeout=10,
    )
    return {"status_code": response.status_code, "body": _safe_json(response)}


def fetch_snap_score(auth_token: str, username: str) -> int | None:
    """
    Fetch the current Snapchat score for *username*.

    Returns the integer score, or None if it cannot be retrieved.
    """
    url = f"https://app.snapchat.com/loq/user_profile?username={username}"
    response = _get(url, headers=_build_headers(auth_token), timeout=10)
    if response.status_code != 200:
        return None
    body = _safe_json(response)
    if isinstance(body, dict):
        return (
            body.get("snap_score")
            or body.get("snapScore")
            or body.get("score")
        )
    return None


# ── Flow ───────────────────────────────────────────────────────────────────────


def flow_increase_score(username: str, auth_token: str) -> None:
    """
    Send snaps in a loop to increase the authenticated user's Snapchat score.

    Steps:
      1. Fetch and display the current score (best-effort).
      2. Ask how many snaps to send and which account to target, then send
         them with a short delay between each to avoid rate limiting, and
         report success / failure for every attempt.
      3. Fetch and display the final score (best-effort).
    """
    # ── Step 1: current score ────────────────────────────────────────────────
    print("\n[INFO] Step 1 — Fetching current Snapchat score …")
    initial_score = fetch_snap_score(auth_token, username)
    if initial_score is not None:
        print(f"[INFO] Current score for @{username}: {initial_score:,}")
    else:
        print("[WARN] Could not fetch current score — proceeding anyway.")

    # ── Step 2: ask for parameters ───────────────────────────────────────────
    recipient_input = input(
        f"\nEnter recipient Snapchat username to send snaps to [default: {username}]: "
    ).strip()
    recipient = recipient_input if recipient_input else username

    count_input = input(
        f"Enter number of snaps to send [default: {DEFAULT_SNAP_COUNT}]: "
    ).strip()
    try:
        count = int(count_input) if count_input else DEFAULT_SNAP_COUNT
        if count < 1:
            raise ValueError
    except ValueError:
        print(f"[WARN] Invalid count — using default of {DEFAULT_SNAP_COUNT}.")
        count = DEFAULT_SNAP_COUNT

    # ── Step 3 & 4: send snaps ───────────────────────────────────────────────
    print(
        f"\n[INFO] Step 2 — Sending {count} snap(s) to @{recipient} "
        f"with {SEND_DELAY_SECONDS}s delay between each …\n"
    )
    ok_count = 0
    fail_count = 0
    for i in range(1, count + 1):
        result = send_snap(auth_token, recipient)
        status = result["status_code"]
        body = result["body"]

        if status in (200, 201):
            print(f"[OK]    Snap {i}/{count} sent successfully.")
            ok_count += 1
        else:
            error_msg = body.get("message", body) if isinstance(body, dict) else body
            print(f"[FAIL]  Snap {i}/{count} → HTTP {status}: {error_msg}")
            fail_count += 1

        if i < count:
            time.sleep(SEND_DELAY_SECONDS)

    # ── Step 5: final score ──────────────────────────────────────────────────
    print(f"\n[INFO] Done. Sent: {ok_count}  |  Failed: {fail_count}")

    print("\n[INFO] Step 3 — Fetching updated Snapchat score …")
    final_score = fetch_snap_score(auth_token, username)
    if final_score is not None:
        gained = (final_score - initial_score) if initial_score is not None else "?"
        print(f"[INFO] Updated score for @{username}: {final_score:,}  (+{gained})")
    else:
        print("[WARN] Could not fetch updated score.")


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    import getpass

    if _CFFI_AVAILABLE:
        print("[INFO] curl_cffi active — Chrome TLS fingerprint (detection bypass on).")
    else:
        print("[WARN] curl_cffi not installed. Snapchat may detect automated requests.")
        print("       Fix: pip install curl_cffi")

    username = input("Enter your Snapchat username: ").strip()
    if not username:
        print("[ERROR] Username cannot be empty.")
        sys.exit(1)

    password = getpass.getpass("Enter your Snapchat password: ").strip()
    if not password:
        print("[ERROR] Password cannot be empty.")
        sys.exit(1)

    print("\n[INFO] Logging in to Snapchat …")
    auth_token = snapchat_login(username, password)
    print("[INFO] Login successful.")

    flow_increase_score(username, auth_token)


if __name__ == "__main__":
    main()
