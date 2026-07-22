"""Aggregation board HTML/CSS/JS, served inline. Polls /api/board every 2s.

One card per game: each team's book fair value(s) + consensus vs the Kalshi
market (bid/ask/mid) with the edge highlighted, and the Kalshi YES ladder. Games
sort by largest absolute edge so the most actionable are on top.
"""

from __future__ import annotations

# ruff: noqa: E501
BOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>thorp board</title>
<style>
  :root{--bg:#0e1116;--panel:#161b22;--panel2:#1c2230;--line:#2a3040;--fg:#e6edf3;
    --muted:#8b949e;--green:#3fb950;--red:#f85149;--amber:#d29922;--blue:#58a6ff;--accent:#bc8cff;}
  *{box-sizing:border-box;} body{margin:0;background:var(--bg);color:var(--fg);
    font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
  header{display:flex;align-items:center;gap:14px;padding:12px 18px;border-bottom:1px solid var(--line);background:var(--panel);flex-wrap:wrap;}
  h1{font-size:15px;margin:0;letter-spacing:.5px;color:var(--accent);}
  .meta{color:var(--muted);font-size:12px;} .spacer{flex:1;}
  main{padding:16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:14px;max-width:1600px;}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;}
  .card h2{font-size:13px;margin:0 0 4px;letter-spacing:.4px;}
  .sub{color:var(--muted);font-size:11px;margin-bottom:8px;}
  table{width:100%;border-collapse:collapse;} th,td{padding:4px 6px;text-align:right;white-space:nowrap;}
  th:first-child,td:first-child{text-align:left;} th{color:var(--muted);font-weight:600;font-size:11px;border-bottom:1px solid var(--line);}
  .pos{color:var(--green);} .neg{color:var(--red);} .zero{color:var(--muted);}
  .edge{font-weight:700;} .big-edge{background:rgba(63,185,80,.12);}
  .pill{padding:1px 6px;border-radius:9px;font-size:10px;border:1px solid var(--line);color:var(--muted);}
  .stale{color:var(--amber);} .ladder{margin-top:8px;display:flex;gap:14px;font-size:11px;color:var(--muted);}
  .ladder div{flex:1;} .lv{display:flex;justify-content:space-between;}
  .empty{color:var(--muted);padding:40px;text-align:center;grid-column:1/-1;}
  .disc{color:var(--amber);padding:40px;text-align:center;font-size:15px;grid-column:1/-1;}
</style></head>
<body>
<header>
  <h1>THORP · BOARD</h1>
  <span id="meta" class="meta"></span>
  <span class="spacer"></span>
  <span class="meta">edge = book fair value minus Kalshi mid, sorted by |edge|</span>
</header>
<main id="root"><div class="disc" id="disc">connecting…</div></main>
<script>
const cents=v=>v==null?"—":(v*100).toFixed(1)+"\\u00A2";
const pct=v=>v==null?"—":(v*100).toFixed(1)+"%";
const edgeTxt=v=>v==null?"—":(v>0?"+":"")+(v*100).toFixed(1)+"\\u00A2";
const cls=v=>v==null?"zero":v>0?"pos":v<0?"neg":"zero";
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const num=v=>v==null?"—":v>=1000?(v/1000).toFixed(0)+"k":v.toFixed(0);

function ladder(team){
  const yes=(team.yes_levels||[]).map(l=>`<div class="lv"><span>${cents(l[0])}</span><span>${num(l[1])}</span></div>`).join("");
  const no=(team.no_levels||[]).map(l=>`<div class="lv"><span>${cents(l[0])}</span><span>${num(l[1])}</span></div>`).join("");
  if(!yes&&!no) return "";
  return `<div class="ladder"><div><b>${esc(team.team)} YES bids</b>${yes||"<div class='lv'>—</div>"}</div>
    <div><b>NO bids</b>${no||"<div class='lv'>—</div>"}</div></div>`;
}

function card(g){
  const stale = g.pinnacle_stale_s!=null && g.pinnacle_stale_s>60;
  const kstale = g.kalshi_stale_s!=null && g.kalshi_stale_s>60;
  const bookCols = g.books.map(b=>`<th>${esc(b)}</th>`).join("");
  const rows = g.teams.map(t=>{
    const fair = g.books.map(b=>`<td>${pct(t.fair_by_book[b])}</td>`).join("");
    const big = t.edge!=null && Math.abs(t.edge)>=0.02 ? "big-edge":"";
    return `<tr class="${big}"><td>${esc(t.team)}</td>${fair}
      <td>${pct(t.consensus)}</td>
      <td>${cents(t.kalshi_bid)} / ${cents(t.kalshi_ask)}</td>
      <td>${cents(t.kalshi_mid)}</td>
      <td class="edge ${cls(t.edge)}">${edgeTxt(t.edge)}</td>
      <td>${num(t.kalshi_volume)}</td></tr>`;
  }).join("");
  const ladders = g.teams.map(ladder).join("");
  return `<div class="card">
    <h2>${esc(g.game_key)}</h2>
    <div class="sub">books: ${g.books.map(esc).join(", ")||"none"}
      ${stale?'<span class="stale">· book stale</span>':''}
      ${g.has_kalshi?(kstale?'<span class="stale">· kalshi stale</span>':''):'<span class="stale">· no kalshi</span>'}</div>
    <table><thead><tr><th>Team</th>${bookCols}<th>Cons.</th><th>Kalshi b/a</th><th>Mid</th><th>Edge</th><th>Vol</th></tr></thead>
    <tbody>${rows}</tbody></table>
    ${ladders}
  </div>`;
}

async function poll(){
  try{
    const s=await (await fetch("/api/board",{cache:"no-store"})).json();
    const root=document.getElementById("root");
    document.getElementById("meta").textContent=`${s.games.length} games · updated ${new Date().toLocaleTimeString()}`;
    if(!s.games.length){root.innerHTML=`<div class="empty">no games captured yet — the collector writes here during pregame windows</div>`;return;}
    root.innerHTML=s.games.map(card).join("");
  }catch(e){
    document.getElementById("root").innerHTML=`<div class="disc">board unreachable: ${e}</div>`;
  }
}
poll(); setInterval(poll, 2000);
</script>
</body></html>"""
