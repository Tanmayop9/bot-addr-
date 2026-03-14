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
Each snap you send adds 1 point to your score; the script automates this in a
loop so you can gain as many points as you like in one run.

### Usage

```bash
python snap_score.py
```

On startup the script prints whether the Chrome TLS bypass is active, then
asks for your credentials:

```
[INFO] curl_cffi active — Chrome TLS fingerprint (detection bypass on).
Enter your Snapchat username:
Enter your Snapchat password:
```

After login it asks two more questions:

```
Enter recipient Snapchat username to send snaps to [default: <your username>]:
Enter number of snaps to send [default: 100]:
```

| Prompt | Description | Default |
|--------|-------------|---------|
| `Enter your Snapchat username:` | Your Snapchat account username | – |
| `Enter your Snapchat password:` | Your Snapchat password (hidden input, never stored) | – |
| `Recipient username` | Account that receives the snaps (can be yourself) | your own username |
| `Number of snaps` | How many snaps to send in this run | `100` |

Steps performed:

1. Authenticate with Snapchat and obtain an auth token.
2. Fetch and display your current Snapchat score.
3. Send the requested number of snaps with a 1-second delay between each.
4. Fetch and display your updated score with the net gain.

### Notes

- The password is read with `getpass` so it will not echo to the terminal.
- No credentials are stored — they are used only in memory for the duration of
  the script.
- The 1-second delay between snaps (`SEND_DELAY_SECONDS`) can be adjusted at
  the top of `snap_score.py` to send faster or slower.
- `curl_cffi` (`pip install curl_cffi`) is strongly recommended to avoid
  detection by Snapchat's bot filters.
