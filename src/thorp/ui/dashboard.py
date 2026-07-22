"""Unified dashboard: Board / Trading / Fills tabs in one page.

Board tab polls ``/api/board`` (multi-source pricing + edge + Kalshi ladder);
Trading tab polls ``/api/state`` (the live sim engine's mode, P&L, positions,
open orders, group caps); Fills tab shows the recent fill stream. One UI to
watch the whole system.
"""

from __future__ import annotations

# ruff: noqa: E501
UI_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>thorp</title>
<style>
  :root{--bg:#0e1116;--panel:#161b22;--panel2:#1c2230;--line:#2a3040;--fg:#e6edf3;
    --muted:#8b949e;--green:#3fb950;--red:#f85149;--amber:#d29922;--blue:#58a6ff;--accent:#bc8cff;}
  *{box-sizing:border-box;} body{margin:0;background:var(--bg);color:var(--fg);
    font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
  header{display:flex;align-items:center;gap:6px;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel);flex-wrap:wrap;}
  h1{font-size:15px;margin:0 14px 0 0;letter-spacing:.5px;color:var(--accent);}
  .tab{padding:6px 14px;border:1px solid var(--line);border-radius:8px;cursor:pointer;color:var(--muted);background:none;font:inherit;}
  .tab.active{color:var(--fg);border-color:var(--blue);background:var(--panel2);}
  .spacer{flex:1;} .meta{color:var(--muted);font-size:12px;}
  main{padding:16px;} .hidden{display:none;}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:14px;max-width:1600px;}
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px;max-width:1200px;}
  .tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;}
  .tile .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.6px;}
  .tile .v{font-size:22px;font-weight:650;margin-top:4px;}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;}
  .card h2{font-size:13px;margin:0 0 4px;} .sub{color:var(--muted);font-size:11px;margin-bottom:8px;}
  section{margin-bottom:22px;} section h2{font-size:12px;text-transform:uppercase;letter-spacing:.7px;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:6px;}
  table{width:100%;border-collapse:collapse;} .scroll{overflow-x:auto;}
  th,td{padding:4px 8px;text-align:right;white-space:nowrap;} th:first-child,td:first-child{text-align:left;}
  th{color:var(--muted);font-weight:600;font-size:11px;border-bottom:1px solid var(--line);}
  tbody tr:nth-child(odd){background:var(--panel);}
  .pos{color:var(--green);} .neg{color:var(--red);} .zero{color:var(--muted);}
  .big-edge{background:rgba(63,185,80,.12);} .badge{padding:2px 10px;border-radius:12px;font-size:12px;border:1px solid var(--line);}
  .mode-SIMULATION{color:var(--blue);border-color:var(--blue);} .halt{color:var(--red);border-color:var(--red);font-weight:700;}
  .ok{color:var(--green);border-color:var(--green);} .stale{color:var(--amber);}
  .empty{color:var(--muted);padding:30px;text-align:center;} .pill{padding:1px 7px;border-radius:10px;font-size:11px;border:1px solid var(--line);}
  .buy_yes{color:var(--green);} .sell_yes{color:var(--red);}
</style></head>
<body>
<header>
  <h1>THORP</h1>
  <button class="tab active" data-tab="board">Board</button>
  <button class="tab" data-tab="trading">Trading</button>
  <button class="tab" data-tab="fills">Fills</button>
  <span class="spacer"></span>
  <span id="meta" class="meta"></span>
</header>
<main>
  <div id="board" class="grid"></div>
  <div id="trading" class="hidden"></div>
  <div id="fills" class="hidden"></div>
</main>
<script>
let TAB="board";
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{
  TAB=b.dataset.tab;
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active",x===b));
  for(const id of ["board","trading","fills"]) document.getElementById(id).classList.toggle("hidden",id!==TAB);
  refresh();
});
const cents=v=>v==null?"—":(v*100).toFixed(1)+"\\u00A2";
const pct=v=>v==null?"—":(v*100).toFixed(1)+"%";
const money=(v,d=2)=>v==null?"—":(v>=0?"+":"")+"$"+v.toFixed(d);
const edgeTxt=v=>v==null?"—":(v>0?"+":"")+(v*100).toFixed(1)+"\\u00A2";
const cls=v=>v==null?"zero":v>0?"pos":v<0?"neg":"zero";
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const num=v=>v==null?"—":v>=1000?(v/1000).toFixed(0)+"k":v.toFixed(0);
const rows=(items,cols,empty)=>!items.length?`<div class="empty">${empty}</div>`:
  `<div class="scroll"><table><thead><tr>${cols.map(c=>`<th>${c.h}</th>`).join("")}</tr></thead>
   <tbody>${items.map(it=>`<tr class="${it._cls||''}">${cols.map(c=>`<td>${c.f(it)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;

function renderBoard(s){
  const root=document.getElementById("board");
  if(!s||!s.games||!s.games.length){root.innerHTML=`<div class="empty">no games captured yet — the engine writes here during pregame windows</div>`;return;}
  root.innerHTML=s.games.map(g=>{
    const cols=[{h:"Team",f:t=>esc(t.team)},...g.books.map(b=>({h:esc(b),f:t=>pct(t.fair_by_book[b])})),
      {h:"Cons.",f:t=>pct(t.consensus)},{h:"Kalshi",f:t=>cents(t.kalshi_mid)},
      {h:"Edge",f:t=>`<span class="${cls(t.edge)}">${edgeTxt(t.edge)}</span>`},{h:"Vol",f:t=>num(t.kalshi_volume)}];
    g.teams.forEach(t=>t._cls=(t.edge!=null&&Math.abs(t.edge)>=0.02)?"big-edge":"");
    return `<div class="card"><h2>${esc(g.game_key)}</h2>
      <div class="sub">books: ${g.books.map(esc).join(", ")||"none"} ${g.has_kalshi?"":"· no kalshi"}</div>
      ${rows(g.teams,cols,"—")}</div>`;
  }).join("");
}
function renderTrading(s){
  const root=document.getElementById("trading");
  if(!s||!s.connected){root.innerHTML=`<div class="empty">${s&&s.reason?esc(s.reason):"engine not running"}</div>`;return;}
  const p=s.pnl;
  const tiles=[["Net P&L (mark-to-mid)",money(p.net),cls(p.net)],["Realized",money(p.realized),cls(p.realized)],
    ["Unrealized",money(p.unrealized),cls(p.unrealized)],["Fees",money(-p.fees_paid),"neg"],
    ["Open orders",s.open_orders.length,""],["Positions",s.positions.filter(x=>x.net_contracts).length,""]]
    .map(([l,v,c])=>`<div class="tile"><div class="l">${l}</div><div class="v ${c}">${v}</div></div>`).join("");
  const pos=rows(s.positions,[{h:"Market",f:x=>esc(x.market_key)},{h:"Net",f:x=>`<span class="${cls(x.net_contracts)}">${x.net_contracts}</span>`},
    {h:"Avg",f:x=>cents(x.avg_entry)},{h:"Mid",f:x=>cents(x.mid)},
    {h:"Unreal",f:x=>`<span class="${cls(x.unrealized)}">${money(x.unrealized)}</span>`},
    {h:"Real",f:x=>`<span class="${cls(x.realized)}">${money(x.realized)}</span>`}],"flat");
  const ords=rows(s.open_orders,[{h:"Market",f:x=>esc(x.market_key)},{h:"Side",f:x=>`<span class="pill ${x.side}">${x.side.replace('_',' ')}</span>`},
    {h:"Price",f:x=>cents(x.price)},{h:"Fill/Sz",f:x=>`${x.filled}/${x.size}`},{h:"State",f:x=>x.state}],"none");
  const grp=rows(s.groups,[{h:"Group",f:x=>esc(x.group)},{h:"Exposure",f:x=>money(x.exposure)},{h:"Hard cap",f:x=>money(x.hard_cap)},
    {h:"Util",f:x=>((x.utilization||0)*100).toFixed(0)+"%"}],"none");
  root.innerHTML=`<div class="tiles">${tiles}</div>
    <section><h2>Positions</h2>${pos}</section>
    <section><h2>Open orders</h2>${ords}</section>
    <section><h2>Group exposure vs caps</h2>${grp}</section>`;
}
function renderFills(s){
  const root=document.getElementById("fills");
  if(!s||!s.connected){root.innerHTML=`<div class="empty">engine not running</div>`;return;}
  root.innerHTML=`<section><h2>Recent fills</h2>${rows(s.fills,[
    {h:"Time",f:x=>esc(x.ts.slice(11,19))},{h:"Market",f:x=>esc(x.market_key)},
    {h:"Side",f:x=>`<span class="pill ${x.side}">${x.side.replace('_',' ')}</span>`},
    {h:"Price",f:x=>cents(x.price)},{h:"Size",f:x=>x.size},{h:"Fee",f:x=>money(-x.fee)},{h:"Liq",f:x=>x.liquidity}],"no fills yet")}</section>`;
}

async function refresh(){
  try{
    if(TAB==="board"){
      const s=await (await fetch("/api/board",{cache:"no-store"})).json();
      document.getElementById("meta").textContent=`${s.games.length} games`;
      renderBoard(s);
    }else{
      const s=await (await fetch("/api/state",{cache:"no-store"})).json();
      if(s.connected){const st=s.stale?`STALE ${s.staleness_s.toFixed(0)}s`:`fresh`;
        document.getElementById("meta").innerHTML=`<span class="badge mode-${s.mode}">${s.mode}</span> ${s.halted?'<span class="badge halt">HALTED</span>':''} ${st}`;}
      else document.getElementById("meta").textContent="engine not running";
      if(TAB==="trading") renderTrading(s); else renderFills(s);
    }
  }catch(e){ document.getElementById("meta").textContent="unreachable: "+e; }
}
refresh(); setInterval(refresh, 2000);
</script></body></html>"""
