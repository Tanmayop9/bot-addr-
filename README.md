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

Add your Discord user tokens to `tokens.txt`, one token per line.  The script
automatically uses the **first token** in the file.

```bash
python add_bots.py
```

On startup the script prints whether the Chrome TLS bypass is active, reads the
first token from `tokens.txt`, and asks for the target guild:

```
[INFO] curl_cffi active — Chrome TLS fingerprint (CAPTCHA bypass on).
[INFO] Using first token from tokens.txt.
Enter the target guild ID [default: 1479676935683575960]:
```

| Prompt | Description | Default |
|--------|-------------|---------|
| `Enter the target guild ID:` | The server to add the bots to | `1479676935683575960` |

> **Note:** `tokens.txt` is listed in `.gitignore` and will never be committed.

Steps performed:

1. Fetch every application/bot you own via the Discord API.
2. Fetch all bots already in the target guild and skip them.
3. Authorise each remaining bot to join the guild with `permissions=8` (Administrator).
4. Print a success or failure message for each bot.

## Notes

- `permissions=8` is the Discord **Administrator** permission integer.
- The token is read from the **first line** of `tokens.txt` (ignored by git via `.gitignore`).
- **CAPTCHA prevention (Termux/Android)** – The primary defence is `curl_cffi`
  (`pip install curl_cffi`) which makes every request look like Chrome 120 at
  the TLS layer.  All Discord API calls also carry a realistic `User-Agent` and
  `X-Super-Properties` header (Chrome/Android) as an additional layer.
