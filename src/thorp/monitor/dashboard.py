"""The dashboard HTML/CSS/JS, served inline (no external assets, no CDN).

Polls ``/api/state`` once a second and re-renders. A monitoring cockpit for a
local sim, deliberately not an Artifact — Artifacts are static and sandboxed and
cannot read the local files the engine writes.
"""

from __future__ import annotations

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>thorp monitor</title>
<style>
  :root {
    --bg:#0e1116; --panel:#161b22; --panel2:#1c2230; --line:#2a3040;
    --fg:#e6edf3; --muted:#8b949e; --green:#3fb950; --red:#f85149;
    --amber:#d29922; --blue:#58a6ff; --accent:#bc8cff;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
    font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
  header { display:flex; align-items:center; gap:16px; flex-wrap:wrap;
    padding:12px 18px; border-bottom:1px solid var(--line); background:var(--panel); }
  h1 { font-size:15px; margin:0; letter-spacing:.5px; color:var(--accent); }
  .badge { padding:2px 10px; border-radius:12px; font-weight:600; font-size:12px;
    border:1px solid var(--line); }
  .mode-SIMULATION { color:var(--blue); border-color:var(--blue); }
  .mode-BACKTEST { color:var(--muted); }
  .mode-CANARY { color:var(--amber); border-color:var(--amber); }
  .mode-PRODUCTION { color:var(--green); border-color:var(--green); }
  .halt { color:var(--red); border-color:var(--red); font-weight:700; }
  .ok { color:var(--green); border-color:var(--green); }
  .spacer { flex:1; }
  .meta { color:var(--muted); font-size:12px; }
  .stale { color:var(--amber); }
  main { padding:16px 18px; max-width:1500px; }
  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
    gap:12px; margin-bottom:18px; }
  .tile { background:var(--panel); border:1px solid var(--line); border-radius:8px;
    padding:12px 14px; }
  .tile .label { color:var(--muted); font-size:11px; text-transform:uppercase;
    letter-spacing:.6px; }
  .tile .val { font-size:22px; font-weight:650; margin-top:4px; }
  .pos { color:var(--green); } .neg { color:var(--red); } .zero { color:var(--muted); }
  section { margin-bottom:22px; }
  h2 { font-size:12px; text-transform:uppercase; letter-spacing:.7px;
    color:var(--muted); margin:0 0 8px; border-bottom:1px solid var(--line);
    padding-bottom:6px; }
  table { width:100%; border-collapse:collapse; }
  .scroll { overflow-x:auto; }
  th,td { text-align:right; padding:5px 10px; white-space:nowrap; }
  th:first-child,td:first-child { text-align:left; }
  th { color:var(--muted); font-weight:600; font-size:11px; border-bottom:1px solid var(--line); }
  tbody tr:nth-child(odd) { background:var(--panel); }
  tbody tr:hover { background:var(--panel2); }
  .pill { padding:1px 7px; border-radius:10px; font-size:11px; border:1px solid var(--line); }
  .buy_yes { color:var(--green); } .sell_yes { color:var(--red); }
  .empty { color:var(--muted); padding:10px; font-style:italic; }
  .tag { color:var(--muted); font-size:11px; }
  .bar { position:relative; height:8px; background:var(--panel2); border-radius:4px;
    overflow:hidden; min-width:90px; display:inline-block; vertical-align:middle; }
  .bar > span { position:absolute; left:0; top:0; bottom:0; background:var(--blue); }
  .bar > span.warn { background:var(--amber); } .bar > span.hot { background:var(--red); }
  .disconnected { color:var(--amber); padding:40px; text-align:center; font-size:15px; }
  .kind-HALT,.kind-REJECT { color:var(--red); } .kind-RESUME { color:var(--green); }
</style>
</head>
<body>
<header>
  <h1>THORP</h1>
  <span id="mode" class="badge">—</span>
  <span id="halt" class="badge ok">RUNNING</span>
  <span class="spacer"></span>
  <span id="meta" class="meta"></span>
</header>
<main id="root">
  <div class="disconnected" id="disc">connecting…</div>
</main>
<script>
const money = (v, dp=2) => v==null ? "—" : (v>=0?"+":"") + "$" + v.toFixed(dp);
const cls = v => v==null ? "zero" : v>0 ? "pos" : v<0 ? "neg" : "zero";
const cents = v => v==null ? "—" : (v*100).toFixed(1) + "\\u00A2";
const ageFmt = s => s<60 ? s.toFixed(0)+"s" : (s/60).toFixed(1)+"m";
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function tile(label, val, klass="") {
  return `<div class="tile"><div class="label">${label}</div>
    <div class="val ${klass}">${val}</div></div>`;
}
function rows(items, cols, empty) {
  if (!items.length) return `<div class="empty">${empty}</div>`;
  const head = "<tr>" + cols.map(c=>`<th>${c.h}</th>`).join("") + "</tr>";
  const body = items.map(it => "<tr>" + cols.map(c=>`<td>${c.f(it)}</td>`).join("") + "</tr>").join("");
  return `<div class="scroll"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}

function render(s) {
  document.getElementById("disc").style.display = "none";
  const modeEl = document.getElementById("mode");
  modeEl.textContent = s.mode; modeEl.className = "badge mode-" + s.mode;
  const haltEl = document.getElementById("halt");
  if (s.halted) { haltEl.textContent = "HALTED: " + (s.halt_reason||""); haltEl.className = "badge halt"; }
  else { haltEl.textContent = "RUNNING"; haltEl.className = "badge ok"; }
  const staleTxt = s.stale ? `<span class="stale">STALE ${s.staleness_s.toFixed(1)}s</span>` :
    `fresh ${s.staleness_s.toFixed(1)}s ago`;
  document.getElementById("meta").innerHTML =
    `uptime ${ageFmt(s.uptime_s)} · seq ${s.last_event_seq} · ${staleTxt}`;

  const p = s.pnl;
  const tiles = tile("Net P&L (mark-to-mid)", money(p.net), cls(p.net))
    + tile("Realized", money(p.realized), cls(p.realized))
    + tile("Unrealized", money(p.unrealized), cls(p.unrealized))
    + tile("Fees paid", money(-p.fees_paid), "neg")
    + tile("Open orders", s.open_orders.length)
    + tile("Positions", s.positions.filter(x=>x.net_contracts!==0).length);

  const positions = rows(s.positions, [
    {h:"Market", f:x=>esc(x.market_key)},
    {h:"Group", f:x=>`<span class="tag">${esc(x.group)}</span>`},
    {h:"Net", f:x=>`<span class="${cls(x.net_contracts)}">${x.net_contracts}</span>`},
    {h:"Avg entry", f:x=>cents(x.avg_entry)},
    {h:"Mid", f:x=>cents(x.mid)},
    {h:"Unrealized", f:x=>`<span class="${cls(x.unrealized)}">${money(x.unrealized)}</span>`},
    {h:"Realized", f:x=>`<span class="${cls(x.realized)}">${money(x.realized)}</span>`},
  ], "flat — no open positions");

  const orders = rows(s.open_orders, [
    {h:"Market", f:x=>esc(x.market_key)},
    {h:"Side", f:x=>`<span class="pill ${x.side}">${x.side.replace('_',' ')}</span>`},
    {h:"Price", f:x=>cents(x.price)},
    {h:"Filled/Size", f:x=>`${x.filled}/${x.size}`},
    {h:"State", f:x=>`<span class="tag">${x.state}</span>`},
    {h:"Age", f:x=>ageFmt(x.age_s)},
    {h:"Model", f:x=>x.fill_model?`<span class="tag">${x.fill_model.queue_position}, +${x.fill_model.modeled_latency_ms}ms</span>`:""},
  ], "no resting orders");

  const groups = rows(s.groups, [
    {h:"Group", f:x=>esc(x.group)},
    {h:"Exposure", f:x=>money(x.exposure)},
    {h:"Soft", f:x=>money(x.soft_cap)},
    {h:"Hard", f:x=>money(x.hard_cap)},
    {h:"Utilization", f:x=>{
      const u = x.utilization||0, pct=(u*100).toFixed(0);
      const k = u>=1?"hot":u>=0.5?"warn":"";
      return `<span class="bar"><span class="${k}" style="width:${Math.min(100,u*100)}%"></span></span> ${pct}%`;
    }},
  ], "no group exposure");

  const fills = rows(s.fills, [
    {h:"Time", f:x=>esc(x.ts.slice(11,19))},
    {h:"Market", f:x=>esc(x.market_key)},
    {h:"Side", f:x=>`<span class="pill ${x.side}">${x.side.replace('_',' ')}</span>`},
    {h:"Price", f:x=>cents(x.price)},
    {h:"Size", f:x=>x.size},
    {h:"Fee", f:x=>money(-x.fee)},
    {h:"Liq", f:x=>`<span class="tag">${x.liquidity}</span>`},
    {h:"Model", f:x=>x.fill_model?`<span class="tag">${x.fill_model.print_allocation}, +${x.fill_model.modeled_latency_ms}ms</span>`:""},
  ], "no fills yet");

  const alerts = rows(s.alerts, [
    {h:"Time", f:x=>esc(x.ts.slice(11,19))},
    {h:"Kind", f:x=>`<span class="kind-${x.kind}">${x.kind}</span>`},
    {h:"Detail", f:x=>esc(x.detail)},
  ], "no rejections or halts");

  document.getElementById("root").innerHTML =
    `<div class="tiles">${tiles}</div>
     <section><h2>Positions · marked to mid</h2>${positions}</section>
     <section><h2>Open orders</h2>${orders}</section>
     <section><h2>Correlated-group exposure vs caps</h2>${groups}</section>
     <section><h2>Recent fills</h2>${fills}</section>
     <section><h2>Rejections &amp; halts</h2>${alerts}</section>`;
}

async function poll() {
  try {
    const r = await fetch("/api/state", {cache:"no-store"});
    const s = await r.json();
    if (s.connected) render(s);
    else {
      const d = document.getElementById("disc");
      d.style.display = "block"; d.textContent = s.reason || "waiting for engine…";
    }
  } catch (e) {
    const d = document.getElementById("disc");
    d.style.display = "block"; d.textContent = "monitor unreachable: " + e;
  }
}
poll(); setInterval(poll, 1000);
</script>
</body>
</html>"""
