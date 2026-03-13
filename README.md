# bot-addr-

A Termux-friendly Discord bot utility — no browser required.

Three features in one script:
1. **Add bots** – Add all Discord bots you own to a target guild.
2. **Create bot** – Create a new bot application, enable all three privileged
   intents, reset its token using your MFA/auth key, and invite it to a guild.
3. **Manage owned bots** – For every bot you own: enable all privileged intents,
   reset the token (TOTP auto-generated), add it to a target guild, and save all
   tokens to `tokens.txt` in one automated pass.

## Requirements

- Python 3.10+
- `requests`, `pyotp`, `curl_cffi` libraries

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
asks for your **Discord user token** (hidden input, never stored) and presents
a menu:

```
[INFO] curl_cffi active — Chrome TLS fingerprint (CAPTCHA bypass on).
Enter your Discord token:

What would you like to do?
  [1] Add all owned bots to a guild
  [2] Create a new bot (enable intents + reset token + invite)
  [3] Manage all owned bots (enable intents + reset tokens + add to guild)
Enter choice [1/2/3, default: 1]:
```

---

### Option 1 – Add all owned bots to a guild

| Prompt | Description | Default |
|--------|-------------|---------|
| `Enter the target guild ID:` | The server to add the bots to | `293939939` |

Steps performed:
1. Fetch every application/bot you own via the Discord API.
2. Authorise each bot to join the guild with `permissions=8` (Administrator).
3. Print a success or failure message for each bot.

---

### Option 2 – Create a new bot

| Prompt | Description | Default |
|--------|-------------|---------|
| `Enter the number of bots you wanna create:` | How many bot applications to create in this run | `1` |
| `Enter a base name for the bot(s):` | Name given to every bot created in this run | – |
| `Enter TOTP secret key:` | Your authenticator's base-32 secret key — the 6-digit code is generated automatically for each bot | skip |
| `Enter NopeCHA API key (or press Enter to skip):` | Optional: auto-solve CAPTCHA via NopeCHA if it is still triggered despite curl_cffi | skip |
| `Add each bot to a guild after creation? [y/N]:` | Optionally auto-invite every created bot | N |
| `Enter the target guild ID:` | (only if auto-invite chosen) | `293939939` |

Steps performed:
1. **Create application** – `POST /applications`.  
   With `curl_cffi` loaded, requests are sent with Chrome's TLS fingerprint and
   a real Android `User-Agent` + `X-Super-Properties` header, which Discord
   treats as a legitimate browser client — CAPTCHA is not triggered.  
   If CAPTCHA is still triggered (rare), it is resolved via:
   - **NopeCHA** (optional) – provide a free API key and the challenge is solved
     silently.  Free tier at [nopecha.com](https://nopecha.com) — no credit card
     needed.
   - **Manual** (fallback) – step-by-step instructions to use **Kiwi Browser**
     (Android browser with DevTools) to extract and paste the token; no PC needed.
2. **Enable all three privileged gateway intents**:
   - Presence Update intent (bit 12)
   - Server Members intent (bit 13)
   - Message Content intent (bit 15)
3. **Reset the bot token** – Provide your TOTP **secret key**
   (e.g. `354n6cs4ptulgduoimkczgz72uv2wh3w`) — the script generates the
   current 6-digit code automatically and passes it via
   `X-Discord-MFA-Authorization`.  
   The new token is printed once and saved to `tokens.txt` — keep both safe.
4. **Invite URL** – Printed in plain text so you can copy it without a browser.
5. Optionally **auto-add to a guild** using the same OAuth2 authorize endpoint.

---

### Option 3 – Manage all owned bots

| Prompt | Description | Default |
|--------|-------------|---------|
| `Enter TOTP secret key:` | Your authenticator's base-32 secret key | – |
| `Enter the target guild ID:` | The server to add every bot to | `1479676935683575960` |

Steps performed for **each** bot you own:
1. **Enable all three privileged gateway intents** (Presence, Guild Members,
   Message Content).
2. **Reset the bot token** using a freshly generated TOTP code — saved to
   `tokens.txt` automatically.
3. **Add to the target guild** with Administrator permissions.

This is the fastest way to bulk-reset tokens and sync all your bots to a
single server in one command.

---

## Notes

- `permissions=8` is the Discord **Administrator** permission integer.
- The token is read with `getpass` so it will not echo to the terminal.
- Bot tokens retrieved via the reset step are **appended to `tokens.txt`** in
  the working directory — one line per bot in the format
  `BotName (ID): TOKEN`.  Keep this file private; add it to `.gitignore`
  (already done in this repo).
- No user credentials are stored — only the bot tokens you explicitly reset.
- MFA is handled via your TOTP **secret key** (the base-32 string shown when
  you first set up 2FA, e.g. `354n6cs4ptulgduoimkczgz72uv2wh3w`). The script
  uses `pyotp` to derive the current 6-digit code automatically — no
  authenticator app needed at runtime.
- **CAPTCHA prevention (Termux/Android)** – The primary defence is `curl_cffi`
  (`pip install curl_cffi`) which makes every request look like Chrome 120 at
  the TLS layer.  This eliminates CAPTCHA for the vast majority of users.  All
  Discord API calls also carry a realistic `User-Agent` and `X-Super-Properties`
  header (Chrome/Android) as an additional layer.
- **CAPTCHA fallback** – If a challenge is still returned, the script can use
  [NopeCHA](https://nopecha.com) (optional API key, free tier — no credit card)
  for automatic solving, or guide you through **Kiwi Browser** (Android Chrome
  with DevTools) to extract and paste the token manually — no PC required.

