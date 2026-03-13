# bot-addr-

A Termux-friendly Discord bot utility — no browser, no CAPTCHA.

Two features in one script:
1. **Add bots** – Add all Discord bots you own to a target guild.
2. **Create bot** – Create a new bot application, enable all three privileged
   intents, reset its token using your MFA/auth key, and invite it to a guild.

## Requirements

- Python 3.10+
- `requests` library

```bash
pip install -r requirements.txt
```

## Usage

```bash
python add_bots.py
```

On startup the script asks for your **Discord user token** (hidden input, never
stored), then presents a menu:

```
What would you like to do?
  [1] Add all owned bots to a guild
  [2] Create a new bot (enable intents + reset token + invite)
Enter choice [1/2, default: 1]:
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

### Option 2 – Create a new bot (Termux-friendly, no CAPTCHA)

| Prompt | Description | Default |
|--------|-------------|---------|
| `Enter the number of bots you wanna create:` | How many bot applications to create in this run | `1` |
| `Enter a base name for the bot(s):` | Name given to every bot created in this run | – |
| `Enter TOTP secret key:` | Your authenticator's base-32 secret key — the 6-digit code is generated automatically for each bot | skip |
| `Enter CapSolver API key:` | CapSolver API key used to automatically solve Discord's hCaptcha if triggered. Get one at [capsolver.com](https://capsolver.com) | skip |
| `Add each bot to a guild after creation? [y/N]:` | Optionally auto-invite every created bot | N |
| `Enter the target guild ID:` | (only if auto-invite chosen) | `293939939` |

Steps performed:
1. **Create application** – `POST /applications`.  
   If Discord returns a CAPTCHA challenge (HTTP 400 with
   `captcha_key: ['captcha-required']`), the script automatically solves it
   via CapSolver (`HCaptchaEnterpriseTaskProxyLess`) and retries the request.
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
- **CAPTCHA handling** – Discord may return an `HTTP 400` CAPTCHA challenge
  (`captcha_key: ['captcha-required']`) when creating a new application.
  The script resolves this automatically using the
  [CapSolver](https://capsolver.com) service
  (`HCaptchaEnterpriseTaskProxyLess` task type).  You need a CapSolver API
  key; CapSolver offers a free tier.  If no key is provided and Discord
  triggers a CAPTCHA, the script will print a clear error and exit.
