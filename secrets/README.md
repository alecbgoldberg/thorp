# secrets/

Everything in this directory is gitignored **except this README and the
`*.env.example` templates**. Your real key IDs and `.pem` private keys live here
and never reach git (verified by the `.gitignore` rules at the repo root).

## Where do I put my API keys? (quick answer)

| Key | File | Variable |
|-----|------|----------|
| Kalshi **read-only** key ID | `secrets/kalshi.env` | `THORP_KALSHI_READONLY_KEY_ID` |
| Kalshi read-only private key | `secrets/kalshi-readonly.pem` | (the `.pem` file itself) |
| Kalshi **full-access** (later) | `secrets/kalshi.env` + `kalshi-full.pem` | `THORP_KALSHI_FULL_*` |
| **OddsPapi** API key | `secrets/odds.env` | `THORP_ODDSPAPI_API_KEY` |
| **Polymarket US** (Ed25519) | `secrets/polymarket.env` + `polymarket-ed25519.pem` | `THORP_POLYMARKET_*` (see docs/17) |

Both `.env` files already exist with labeled paste spots — just open and paste.
Real environment variables override the files, so on a server you can set the
vars in the environment and skip the files entirely.

## The two-key model (why there are two)

You asked for a read-only key for the sim and a full-access key for prod. Kalshi
supports exactly this at the API level, so we lean on it as a real safety layer,
not just a naming convention:

| Key | Kalshi scopes | Used by | Can it place an order? |
|-----|---------------|---------|------------------------|
| **READ-ONLY** | `read` only | Recorder, BACKTEST, **SIMULATION** | **No** — Kalshi rejects any order with 403 |
| **FULL** | `read` + `write::trade` | **CANARY / PRODUCTION** live venue only | Yes (trade only; no withdraw) |

This is defense-in-depth. The `ShadowVenue` already can't send orders by type
(Doc 3 §4), and the code refuses to hand a full-access key to a sim run
(`thorp.common.secrets.require_credential`). The read-only key means that even
if *both* of those failed, Kalshi itself still rejects the order. Three
independent layers; the key scope is the one Kalshi enforces server-side.

## Setup — read-only key (do this first; it's all the Recorder/sim need)

1. Kalshi dashboard → **API Keys** → **Create key**. Grant the **`read`** scope
   **only** (no `write`).
2. Copy the **Key ID** (a UUID-looking string) into `THORP_KALSHI_READONLY_KEY_ID`
   in `secrets/kalshi.env`.
3. Download the private key it gives you and save it here as
   `secrets/kalshi-readonly.pem`. (That's the default path in the env file; put
   it elsewhere and update `THORP_KALSHI_READONLY_PRIVATE_KEY` to match.)

That's it — `cp secrets/kalshi.env.example secrets/kalshi.env` is already done
for you (the real `kalshi.env` exists with placeholders); just paste into it.

## Setup — full-access key (LATER, only before funding a live account)

- Create a second key with **`read` + `write::trade`**. **Do not** enable
  withdraw/transfer scopes — the bot never needs to move money out.
- Optional but recommended: restrict the key to a single **sub-account** (Kalshi
  supports `subaccount` 0–63), and fund only that sub-account, so even a
  worst-case bug is bounded to trading funds.
- Save as `secrets/kalshi-full.pem`, paste the Key ID into
  `THORP_KALSHI_FULL_KEY_ID`. Leave these blank until Phase 3.

## How the code reads these

`secrets/kalshi.env` is loaded at process startup (`load_env_file`), but **real
environment variables always win** — so on a server you can set the vars in the
environment and skip the file. Either way, code asks for a *scope*
(`CredentialScope.READ_ONLY` / `FULL_ACCESS`), never a raw key, and the resolver
maps it to the right pair. A sim can't accidentally request the full key.

## Formats accepted for the private-key value

Either a **path** to a `.pem` file (default), or the **PEM text pasted inline**
(single line, with `\n` for newlines) if you'd rather keep it all in the env
file. Paths are the tidy default; inline exists for containerized deploys.

## OddsPapi (and future odds providers)

`secrets/odds.env` holds odds-provider keys. Only OddsPapi is wired up today
(free tier — get a key at https://oddspapi.io and paste it into
`THORP_ODDSPAPI_API_KEY`). The provider is **swappable** (`src/thorp/odds/`):
switching to a different vendor later is a config change plus adding that
vendor's key here — no caller code changes. These are read-only *signal*
sources; they are never on any order path (Kalshi-only execution stands).

## If a key is ever exposed

Revoke it in the Kalshi dashboard immediately and create a new one — key
rotation is a portal action (generate new → swap → revoke old). The position and
loss limits (Doc 4) bound the damage even in the window before rotation.
