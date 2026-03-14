# bot-addr-

A Termux-friendly Discord bot adder — no browser required.

Adds all Discord bots you own to a target guild.  Bots already present in the
guild are skipped automatically to avoid rate limiting.

## Requirements

- Python 3.10+
- `requests`, `curl_cffi` libraries

```bash
pip install -r requirements.txt
```

`curl_cffi` is the key dependency for Termux users — it makes the script
impersonate Chrome's TLS fingerprint so Discord does **not** trigger a CAPTCHA
in the first place.  The script still works without it, but CAPTCHA is more
likely.

## Usage

```bash
python add_bots.py
```

On startup the script prints whether the Chrome TLS bypass is active, then
asks for your **Discord user token** (hidden input, never stored):

```
[INFO] curl_cffi active — Chrome TLS fingerprint (CAPTCHA bypass on).
Enter your Discord token:
Enter the target guild ID [default: 1479676935683575960]:
```

| Prompt | Description | Default |
|--------|-------------|---------|
| `Enter your Discord token:` | Your Discord user token (hidden, never stored) | – |
| `Enter the target guild ID:` | The server to add the bots to | `1479676935683575960` |

Steps performed:

1. Fetch every application/bot you own via the Discord API.
2. Fetch all bots already in the target guild and skip them.
3. Authorise each remaining bot to join the guild with `permissions=8` (Administrator).
4. Print a success or failure message for each bot.

## Notes

- `permissions=8` is the Discord **Administrator** permission integer.
- The token is read with `getpass` so it will not echo to the terminal.
- No credentials are stored — the token is used only in memory for the
  duration of the script.
- **CAPTCHA prevention (Termux/Android)** – The primary defence is `curl_cffi`
  (`pip install curl_cffi`) which makes every request look like Chrome 120 at
  the TLS layer.  All Discord API calls also carry a realistic `User-Agent` and
  `X-Super-Properties` header (Chrome/Android) as an additional layer.

---

## Snapchat Score Increaser

`snap_score.py` sends snaps on your behalf to increase your Snapchat score.
It is a fully interactive, advanced tool with live progress, auto-retry,
batch control, and a full session summary.

### Features

- **No hidden inputs** — all prompts are visible as you type
- **Multiple recipients** — spread snaps across a comma-separated list of usernames
- **Randomised delays** — configurable min/max inter-snap pause to avoid detection
- **Batch mode** — send N snaps, pause for a configurable interval, then continue
- **Auto-retry with back-off** — retries 429 / 5xx failures with exponential back-off; honours `Retry-After` headers automatically
- **Live ASCII progress bar** — shows `done/total`, success/fail counts, and ETA
- **Verbose flag** — optionally print full API response bodies for debugging
- **Session summary** — snaps sent, failed, retries, elapsed time, and score Δ

### Usage

```bash
python snap_score.py
```

On startup the script prints whether the Chrome TLS bypass is active, then
asks for your credentials (all inputs are visible):

```
[INFO] curl_cffi active — Chrome TLS fingerprint (detection bypass on).
Enter your Snapchat username:
Enter your Snapchat password:
```

After login it asks for run parameters:

```
[CONFIG] Configure this run (press Enter to accept defaults)

  Recipients (comma-separated usernames) [default: <your username>]:
  Total snaps to send [default: 100]:
  Min delay between snaps (s) [default: 0.8]:
  Max delay between snaps (s) [default: 2.0]:
  Batch size (snaps before a longer pause) [default: 20]:
  Pause between batches (s) [default: 10.0]:
  Max retries per snap on failure [default: 3]:
  Verbose output? (y/N):
```

| Prompt | Description | Default |
|--------|-------------|---------|
| `Recipients` | Comma-separated Snapchat usernames to receive snaps | your own username |
| `Total snaps` | Total number of snaps to send in this run | `100` |
| `Min delay` | Lower bound of the randomised pause between snaps (seconds) | `0.8` |
| `Max delay` | Upper bound of the randomised pause between snaps (seconds) | `2.0` |
| `Batch size` | Snaps per batch before the longer batch pause | `20` |
| `Batch pause` | Seconds to wait between batches | `10.0` |
| `Max retries` | How many times to retry a snap on 429/5xx before marking it failed | `3` |
| `Verbose` | Print full API response bodies (`y` / `N`) | `N` |

Steps performed:

1. Authenticate with Snapchat and obtain an auth token.
2. Fetch and display your current Snapchat score.
3. Send snaps in batches, cycling across all recipients, with randomised
   delays and automatic retry/back-off — a live progress bar updates in place.
4. Fetch and display your updated score with the net gain.
5. Print a full session-stats table.

### Notes

- **All inputs are plain `input()` — nothing is hidden.** This means the
  password is visible as you type.  Only run on a private terminal — avoid
  shared machines, screen-recording sessions, or systems with terminal logging.
- No credentials are stored — they are used only in memory for the duration
  of the script.
- `curl_cffi` (`pip install curl_cffi`) is strongly recommended to avoid
  detection by Snapchat's bot filters.
