# bot-addr-

A utility script that adds all Discord bots owned by a user to a target guild
with permissions=8 (Administrator).

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

The script will interactively prompt you for:

| Prompt | Description | Default |
|--------|-------------|---------|
| `Enter your Discord token:` | Your Discord user token (hidden input, not stored) | – |
| `Enter the target guild ID:` | The server to add the bots to | `293939939` |

It will then:
1. Fetch every application/bot you own via the Discord API.
2. Authorise each bot to join the guild with `permissions=8` (Administrator).
3. Print a success or failure message for each bot.

No credentials are stored anywhere — everything lives only in memory for the
duration of the script.

## Notes

- `permissions=8` is the Discord **Administrator** permission integer.
- The token is read with `getpass` so it will not echo to the terminal.
