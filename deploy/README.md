# deploy/ — headless tracker

Runs the MLB moneyline lead/lag tracker (`python -m thorp.tracker`) as a
background **launchd LaunchAgent** on macOS, wrapped in `caffeinate` so the Mac
doesn't idle-sleep while it captures.

```sh
deploy/install-tracker.sh install     # write the agent, load it, start capturing
deploy/install-tracker.sh status      # running?
deploy/install-tracker.sh logs        # follow the tracker's log
deploy/install-tracker.sh uninstall   # stop and remove
```

- **Auto-restart**: `KeepAlive` restarts the tracker if it exits or crashes
  (throttled to once a minute).
- **Survives logout / terminal close**: it's a launchd agent, not tied to your
  shell.
- **Budget-safe**: the tracker's own monthly OddsPapi budget guard (250 calls)
  applies regardless of how long it runs; it only calls Pinnacle in the active
  window around first pitch.

## The sleep caveat (important)

`caffeinate -is` prevents **idle** and **system** sleep while the tracker runs,
so on **AC power** it keeps going when the Mac would otherwise nap. It does
**not** defeat a hard lid-close on battery, and macOS can still suspend in some
low-power states. For genuine 24/7 capture, run this on a small always-on box
(the Doc 5 recommendation: Hetzner CX22 ~$5/mo or AWS Lightsail nano) — the
tracker is plain Python + `uv`, so `git clone`, drop `secrets/odds.env`, and run
`python -m thorp.tracker` there. Ask and I'll write that provisioning step once
you have a host.

## What it writes

- `data/tracker/observations/date=*.jsonl` — paired Kalshi/Pinnacle probability
  observations (the lead/lag study's input).
- `data/odds_budget.json` — persistent monthly OddsPapi call count.
- `logs/tracker.log` (+ `logs/tracker.out/err.log`) — leveled run log.
