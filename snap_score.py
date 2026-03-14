"""
snap_score.py – Advanced Snapchat score increaser (Termux-friendly).

Sends snaps on your behalf to increase your Snapchat score.
Features:
  • Multiple recipients (comma-separated)
  • Randomised delays (configurable min/max) for stealth
  • Auto-retry with exponential back-off on 429 / 5xx responses
  • Batch mode — send N snaps, pause, repeat
  • Live ASCII progress bar with ETA
  • Rate-limit auto-detection and automatic cooldown
  • Verbose flag to print full response bodies
  • Full session stats at the end (sent, failed, retried, elapsed, score Δ)

Usage:
    python snap_score.py
"""

import itertools
import random
import ssl
import sys
import time
import uuid

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

# Optional: curl_cffi impersonates Chrome's TLS fingerprint so Snapchat does
# not flag automated requests.  Install once with:  pip install curl_cffi
try:
    from curl_cffi import requests as _cffi_requests
    _CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CFFI_AVAILABLE = False


class _SSLAdapter(HTTPAdapter):
    """HTTPAdapter that tolerates unexpected TLS EOF (Python ≥ 3.12 / OpenSSL ≥ 3).

    Some servers (including auth.snapchat.com) close the TLS connection without
    sending a ``close_notify`` alert.  Python 3.12 made the OpenSSL default
    stricter about this, causing ``ssl.SSLEOFError: UNEXPECTED_EOF_WHILE_READING``.
    Setting ``OP_IGNORE_UNEXPECTED_EOF`` (added in Python 3.11) restores the
    lenient behaviour so those servers keep working.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        # OP_IGNORE_UNEXPECTED_EOF is only available on Python ≥ 3.11.
        # On older Pythons the flag doesn't exist and also isn't needed.
        ctx.options |= getattr(ssl, "OP_IGNORE_UNEXPECTED_EOF", 0)
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


# A shared requests session that mounts the SSL-tolerant adapter for all HTTPS
# requests.  Only used when curl_cffi is not available.
_requests_session = requests.Session()
_requests_session.mount("https://", _SSLAdapter())

# ── Constants ──────────────────────────────────────────────────────────────────

SNAPCHAT_AUTH_URL  = "https://auth.snapchat.com/login"
SNAPCHAT_SEND_URL  = "https://app.snapchat.com/loq/send_message"
SNAPCHAT_PROFILE_URL = "https://app.snapchat.com/loq/user_profile"

_IMPERSONATE = "chrome120"

_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; K) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

# Defaults (all overridable at runtime via prompts)
DEFAULT_SNAP_COUNT   = 100
DEFAULT_DELAY_MIN    = 0.8    # seconds — lower bound of randomised inter-snap pause
DEFAULT_DELAY_MAX    = 2.0    # seconds — upper bound
DEFAULT_BATCH_SIZE   = 20     # snaps per batch
DEFAULT_BATCH_PAUSE  = 10.0   # seconds between batches
DEFAULT_MAX_RETRIES  = 3      # retry attempts per snap on transient failure
DEFAULT_BACKOFF_BASE = 2.0    # exponential back-off base (seconds)

# HTTP status codes that are safe to retry
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# ── HTTP helpers ───────────────────────────────────────────────────────────────


def _get(url: str, **kwargs):
    """HTTP GET — uses curl_cffi Chrome impersonation when available."""
    if _CFFI_AVAILABLE:
        return _cffi_requests.get(url, impersonate=_IMPERSONATE, **kwargs)
    return _requests_session.get(url, **kwargs)


def _post(url: str, **kwargs):
    """HTTP POST — uses curl_cffi Chrome impersonation when available."""
    if _CFFI_AVAILABLE:
        return _cffi_requests.post(url, impersonate=_IMPERSONATE, **kwargs)
    return _requests_session.post(url, **kwargs)


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
    """Build Snapchat API request headers with a fresh request ID each time."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "User-Agent": _USER_AGENT,
        "X-Snapchat-Client-Auth-Token": auth_token,
        "X-Request-ID": str(uuid.uuid4()),
        "Accept-Language": "en-US,en;q=0.9",
    }


def _progress_bar(done: int, total: int, ok: int, fail: int,
                  elapsed: float, width: int = 30) -> str:
    """
    Return a single-line ASCII progress bar, e.g.:

        [==========>         ] 55/100 (55%) | ✓ 54  ✗ 1 | ETA: 37s
    """
    pct = done / total if total else 0
    filled = min(int(width * pct), width)
    if filled >= width:
        bar = "=" * width
    else:
        bar = "=" * filled + ">" + " " * (width - filled - 1)
    rate = done / elapsed if elapsed > 0 else 0
    eta_s = int((total - done) / rate) if rate > 0 else 0
    eta = f"{eta_s}s" if rate > 0 else "?"
    return (
        f"[{bar}] {done}/{total} ({pct:.0%}) "
        f"| ✓ {ok}  ✗ {fail} | ETA: {eta}"
    )


def _ask_int(prompt: str, default: int) -> int:
    """Prompt for an integer with a default; re-prompt on bad input."""
    while True:
        raw = input(f"{prompt} [default: {default}]: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
            if val >= 1:
                return val
            print("  [WARN] Value must be ≥ 1 — try again.")
        except ValueError:
            print("  [WARN] Enter a whole number — try again.")


def _ask_float(prompt: str, default: float) -> float:
    """Prompt for a float with a default; re-prompt on bad input."""
    while True:
        raw = input(f"{prompt} [default: {default}]: ").strip()
        if not raw:
            return default
        try:
            val = float(raw)
            if val >= 0:
                return val
            print("  [WARN] Value must be ≥ 0 — try again.")
        except ValueError:
            print("  [WARN] Enter a number — try again.")


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


def send_snap_with_retry(
    auth_token: str,
    recipient: str,
    max_retries: int,
    backoff_base: float,
    verbose: bool,
) -> tuple[bool, int]:
    """
    Send a single snap to *recipient*, retrying on transient failures.

    Returns ``(success: bool, retries_used: int)``.
    On a 429 (rate-limit) the script waits for the ``Retry-After`` header value
    (or falls back to exponential back-off) before trying again.
    """
    media_id = str(uuid.uuid4()).upper()
    payload = {
        "media_id": media_id,
        "recipient_ids": [recipient],
        "type": "IMAGE",
        "capture_duration_secs": 3,
        "timer_duration_secs": 3,
        "story_metadata": {},
    }

    for attempt in range(max_retries + 1):
        response = _post(
            SNAPCHAT_SEND_URL,
            json=payload,
            headers=_build_headers(auth_token),
            timeout=10,
        )
        status = response.status_code
        body   = _safe_json(response)

        if verbose:
            print(f"         [VERBOSE] HTTP {status}  body={body}")

        if status in (200, 201):
            return True, attempt

        if status in _RETRYABLE_STATUSES and attempt < max_retries:
            # Honour Retry-After when present (e.g. on 429).
            # The header value may be an integer delay or an HTTP-date string;
            # fall back to exponential back-off if it cannot be parsed as float.
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = float(retry_after)
                    print(f"\n  [RATE-LIMIT] Cooling down for {wait:.0f}s (Retry-After) …")
                except ValueError:
                    wait = backoff_base * (2 ** attempt) + random.uniform(0, 0.5)
                    print(f"\n  [RATE-LIMIT] Back-off {wait:.1f}s (Retry-After unparseable) …")
            else:
                wait = backoff_base * (2 ** attempt) + random.uniform(0, 0.5)
                if status == 429:
                    print(f"\n  [RATE-LIMIT] Back-off {wait:.1f}s before retry …")
                else:
                    print(f"\n  [RETRY] HTTP {status} — back-off {wait:.1f}s …")
            time.sleep(wait)
            continue

        # Non-retryable failure
        if verbose:
            msg = body.get("message", body) if isinstance(body, dict) else body
            print(f"         [FAIL-DETAIL] {msg}")
        return False, attempt

    return False, max_retries


def fetch_snap_score(auth_token: str, username: str) -> int | None:
    """
    Fetch the current Snapchat score for *username*.

    Returns the integer score, or None if it cannot be retrieved.
    """
    url = f"{SNAPCHAT_PROFILE_URL}?username={username}"
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
    Interactive flow that sends snaps in batches to boost the Snapchat score.

    Steps:
      1. Fetch and display the current score (best-effort).
      2. Collect all run parameters from the user.
      3. Send snaps in batches with randomised delays and auto-retry; display a
         live progress bar after each snap.
      4. Fetch and display the final score with the net gain.
      5. Print a full session-stats summary.
    """
    # ── Step 1: current score ────────────────────────────────────────────────
    print("\n[INFO] Step 1 — Fetching current Snapchat score …")
    initial_score = fetch_snap_score(auth_token, username)
    if initial_score is not None:
        print(f"[INFO] Current score for @{username}: {initial_score:,}")
    else:
        print("[WARN] Could not fetch current score — proceeding anyway.")

    # ── Step 2: collect parameters ───────────────────────────────────────────
    print("\n[CONFIG] Configure this run (press Enter to accept defaults)\n")

    recipients_raw = input(
        f"  Recipients (comma-separated usernames) [default: {username}]: "
    ).strip()
    recipients: list[str] = (
        [r.strip() for r in recipients_raw.split(",") if r.strip()]
        if recipients_raw
        else [username]
    )
    print(f"  → Sending to: {', '.join('@' + r for r in recipients)}")

    count       = _ask_int("  Total snaps to send", DEFAULT_SNAP_COUNT)
    delay_min   = _ask_float("  Min delay between snaps (s)", DEFAULT_DELAY_MIN)
    # Ensure the default for delay_max is always strictly greater than delay_min.
    delay_max_default = max(delay_min + 0.1, DEFAULT_DELAY_MAX)
    while True:
        delay_max = _ask_float("  Max delay between snaps (s)", delay_max_default)
        if delay_max >= delay_min:
            break
        print(f"  [WARN] Max delay must be ≥ min delay ({delay_min}s) — try again.")
    batch_size  = _ask_int("  Batch size (snaps before a longer pause)", DEFAULT_BATCH_SIZE)
    batch_pause = _ask_float("  Pause between batches (s)", DEFAULT_BATCH_PAUSE)
    max_retries = _ask_int("  Max retries per snap on failure", DEFAULT_MAX_RETRIES)
    verbose_raw = input("  Verbose output? (y/N): ").strip().lower()
    verbose     = verbose_raw in ("y", "yes")

    # ── Step 3: send snaps ───────────────────────────────────────────────────
    print(
        f"\n[INFO] Step 2 — Sending {count} snap(s) to "
        f"{len(recipients)} recipient(s) …\n"
    )

    ok_count      = 0
    fail_count    = 0
    retry_total   = 0
    start_time    = time.monotonic()

    # Cycle through recipients so snaps are spread evenly across all of them.
    recipient_cycle = itertools.cycle(recipients)

    for i in range(1, count + 1):
        recipient = next(recipient_cycle)
        success, retries = send_snap_with_retry(
            auth_token, recipient, max_retries, DEFAULT_BACKOFF_BASE, verbose
        )
        retry_total += retries

        if success:
            ok_count += 1
        else:
            fail_count += 1

        elapsed = time.monotonic() - start_time
        bar = _progress_bar(i, count, ok_count, fail_count, elapsed)
        # Overwrite the current line for a live updating effect.
        print(f"\r  {bar}", end="", flush=True)

        # Pause between batches (but not after the very last snap).
        if i < count:
            if i % batch_size == 0:
                print(f"\n  [BATCH] Batch of {batch_size} done — pausing {batch_pause}s …")
                time.sleep(batch_pause)
            else:
                delay = random.uniform(delay_min, delay_max)
                time.sleep(delay)

    print()  # newline after the progress bar

    # ── Step 4: final score ──────────────────────────────────────────────────
    print("\n[INFO] Step 3 — Fetching updated Snapchat score …")
    final_score = fetch_snap_score(auth_token, username)
    if final_score is not None:
        gained = (final_score - initial_score) if initial_score is not None else "?"
        print(f"[INFO] Updated score for @{username}: {final_score:,}  (+{gained})")
    else:
        print("[WARN] Could not fetch updated score.")

    # ── Step 5: session summary ──────────────────────────────────────────────
    elapsed_total = time.monotonic() - start_time
    mins, secs = divmod(int(elapsed_total), 60)
    elapsed_fmt = f"{mins}m {secs}s" if mins else f"{secs}s"

    print("\n" + "─" * 48)
    print("  SESSION SUMMARY")
    print("─" * 48)
    print(f"  Snaps sent successfully : {ok_count:>6,}")
    print(f"  Snaps failed            : {fail_count:>6,}")
    print(f"  Total retry attempts    : {retry_total:>6,}")
    print(f"  Recipients targeted     : {len(recipients):>6,}")
    print(f"  Total elapsed time      : {elapsed_fmt:>6}")
    if initial_score is not None and final_score is not None:
        delta = final_score - initial_score
        print(f"  Score gained            : {delta:>+6,}")
    print("─" * 48)


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    if _CFFI_AVAILABLE:
        print("[INFO] curl_cffi active — Chrome TLS fingerprint (detection bypass on).")
    else:
        print("[WARN] curl_cffi not installed. Snapchat may detect automated requests.")
        print("       Fix: pip install curl_cffi")

    print(
        "[WARN] Credentials are entered as visible text. "
        "Do not use on shared or screen-recorded terminals."
    )

    username = input("Enter your Snapchat username: ").strip()
    if not username:
        print("[ERROR] Username cannot be empty.")
        sys.exit(1)

    password = input("Enter your Snapchat password: ").strip()
    if not password:
        print("[ERROR] Password cannot be empty.")
        sys.exit(1)

    print("\n[INFO] Logging in to Snapchat …")
    auth_token = snapchat_login(username, password)
    print("[INFO] Login successful.")

    flow_increase_score(username, auth_token)


if __name__ == "__main__":
    main()
