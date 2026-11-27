"use strict";
const TZ="Europe/Vienna",DAYS=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
let D=null,range="day",sel=null;
const $=s=>document.querySelector(s);
const fmt=(d,o)=>new Intl.DateTimeFormat("en-GB",Object.assign({timeZone:TZ},o)).format(d);
const parts=d=>{const p={};new Intl.DateTimeFormat("en-GB",{timeZone:TZ,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",weekday:"short",hourCycle:"h23"}).formatToParts(d).forEach(x=>p[x.type]=x.value);
 return {date:`${p.year}-${p.month}-${p.day}`,h:+p.hour,m:+p.minute,wd:["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].indexOf(p.weekday)}};
const tzLabel=d=>fmt(d,{timeZoneName:"short"}).split(" ").pop();
const median=a=>{const s=[...a].sort((x,y)=>x-y),n=s.length;return n?(n%2?s[(n-1)/2]:(s[n/2-1]+s[n/2])/2):null};
const ago=ms=>{const m=Math.round(ms/6e4);return m<60?`${m} min`:m<1440?`${Math.floor(m/60)} h ${m%60} min`:`${Math.floor(m/1440)} d`};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function addDays(ds,n){const d=new Date(ds+"T12:00:00Z");d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10)}
function inRange(o){const ds=o.p.date;if(range==="all")return true;if(range==="day")return ds===sel;
 if(range==="week"){const wd=new Date(sel+"T12:00:00Z").getUTCDay(),mon=addDays(sel,-((wd+6)%7));return ds>=mon&&ds<=addDays(mon,6)}
 return ds.slice(0,7)===sel.slice(0,7)}
async function load(){
 try{const r=await fetch("data.json?ts="+Date.now(),{cache:"no-store"});if(!r.ok)throw new Error(r.status);
  const j=await r.json();j.observations.forEach(o=>{o.d=new Date(o.t);o.p=parts(o.d)});D=j;
  if(!sel){const ok=D.observations.filter(o=>o.s==="ok");sel=ok.length?ok[ok.length-1].p.date:parts(new Date()).date;$("#date").value=sel}
  render();
 }catch(e){const s=$("#status");s.className="status err";s.textContent="Could not refresh data ("+e.message+"); showing last loaded values"}}
function status(){const ok=D.observations.filter(o=>o.s==="ok"),s=$("#status"),now=Date.now();
 if(!ok.length){s.textContent="No observations yet";return}
 const L=ok[ok.length-1],age=now-L.d,gen=new Date(D.generated_utc);
 const p=parts(new Date()),open=p.h>=6&&p.h<23,stale=open&&age>40*6e4;
 s.className="status"+(stale?" stale":"");
 s.innerHTML=`Latest observed: <b>${L.c}</b> at ${fmt(L.d,{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})} ${tzLabel(L.d)} (${ago(age)} ago)${stale?" — snapshot may be stale":""}<br><small>Snapshot generated ${fmt(gen,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})} ${tzLabel(gen)} · checked ${fmt(new Date(),{hour:"2-digit",minute:"2-digit",second:"2-digit"})}</small>`}
function kpis(obs){const ok=obs.filter(o=>o.s==="ok"),fails=obs.length-ok.length,el=$("#kpis");
 if(!ok.length){el.innerHTML=`<div class="kpi"><b>–</b><span>No successful readings in this range</span></div>`;return}
 const c=ok.map(o=>o.c),mn=Math.min(...c),mx=Math.max(...c),avg=c.reduce((a,b)=>a+b,0)/c.length;
 const at=v=>ok.filter(o=>o.c===v).slice(0,3).map(o=>fmt(o.d,range==="day"?{hour:"2-digit",minute:"2-digit"}:{weekday:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})).join(", ")+(ok.filter(o=>o.c===v).length>3?"…":"");
 el.innerHTML=[[mn,"Min · "+at(mn)],[mx,"Max · "+at(mx)],[avg.toFixed(1),"Average of readings"],[median(c),"Median"],[ok.length,"Readings"+(fails?` · ${fails} failed`:"")],[new Set(ok.map(o=>o.p.date)).size,"Distinct dates"]]
 .map(([v,l])=>`<div class="kpi"><b>${v}</b><span>${esc(l)}</span></div>`).join("")}

const WEEKDAYS=["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
const CHART_NOTE="Dots are real readings at their actual time (Europe/Vienna). Lines only join neighbouring readings — not continuous measurement, no smoothing, no forecast. Gaps over 25 min are dashed; failed reads are marked ×.";
function weekdayName(ds){return WEEKDAYS[new Date(ds+"T12:00:00Z").getUTCDay()]}
function typicalOf(ds){return D&&D.typical&&D.typical.weekdays?D.typical.weekdays[weekdayName(ds)]||null:null}
function minsOf(slot){const[h,m]=slot.split(":").map(Number);return h*60+m}
function adjacent(a,b){return minsOf(b)-minsOf(a)===15}
function slotOfReading(o){return String(o.p.h).padStart(2,"0")+":"+String(o.p.m-o.p.m%15).padStart(2,"0")}
function basisOf(typ){if(!typ)return "all days";return typ.source==="weekday"?("on "+["Mondays","Tuesdays","Wednesdays","Thursdays","Fridays","Saturdays","Sundays"][["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"].indexOf(typ.weekday)]):"all days"}
function usualCategory(count,slot){if(!slot||slot.lo==null||slot.hi==null)return null;if(count<slot.lo)return "quieter than usual";if(count>slot.hi)return "busier than usual";return "about usual"}
function roundHalfUp(v){return Math.floor(v+0.5)}
function typicalNotes(obs){
 const title=$("#chartTitle"),bar=$("#vsBar"),legend=$("#vsLegend"),noteEl=$("#chartNote"),foot=$("#vsFoot"),pill=$("#vsPill"),meta=$("#vsMeta");
 const day=range==="day";
 if(bar) bar.hidden=!day; if(legend) legend.hidden=!day; if(foot){foot.hidden=!day; foot.textContent=""}
 if(title) title.textContent=day?dayTitle():"Observed counts over time";
 if(!day){if(noteEl) noteEl.textContent=CHART_NOTE; return}
 const ok=(obs||[]).filter(o=>o.s==="ok"),typ=typicalOf(sel),latest=ok.length?ok[ok.length-1]:null;
 const basis=basisOf(typ);
 if(noteEl) noteEl.textContent=typ?`Historical median and middle 50% · ${basis} · Europe/Vienna`:"No typical curve yet.";
 if(foot&&ok.length){
  const low=ok.reduce((a,o)=>!a||o.c<a.c||(o.c===a.c&&o.d<a.d)?o:a,null);
  const high=ok.reduce((a,o)=>!a||o.c>a.c||(o.c===a.c&&o.d<a.d)?o:a,null);
  const hm=o=>fmt(o.d,{hour:"2-digit",minute:"2-digit"});
  foot.textContent=`Lowest observed ${low.c} at ${hm(low)} | Highest observed ${high.c} at ${hm(high)} | ${ok.length} readings`;
 }
 if(!pill||!meta) return;
 pill.hidden=true; meta.textContent="";
 if(!typ||!latest) return;
 const slot=(typ.slots||[]).find(s=>s.slot===slotOfReading(latest));
 if(!slot) return;
 const shown=roundHalfUp(slot.median),cat=usualCategory(latest.c,slot);
 if(cat){pill.hidden=false;pill.textContent=cat}
 meta.textContent=`Historical median: ${shown} · Updated ${fmt(latest.d,{hour:"2-digit",minute:"2-digit"})}`;
}
function dayTitle(){const today=parts(new Date()).date;if(sel===today)return "Today vs usual";
 const d=new Date(sel+"T12:00:00Z");return fmt(d,{weekday:"short",day:"numeric",month:"short"}).replace(",","")+" vs usual"}
function typicalRuns(slots){
 const runs=[]; let cur=[];
 const flush=()=>{if(cur.length>=2) runs.push(cur); cur=[]};
 slots.forEach(s=>{if(cur.length&&!adjacent(cur[cur.length-1].slot,s.slot)) flush(); cur.push(s)});
 flush(); return runs;
}
function typicalLayer(typ,x,y){
 if(!typ||!typ.slots||!typ.slots.length) return "";
 let g="";
 typicalRuns(typ.slots).forEach(run=>{
  let band=[];
  const flushBand=()=>{
   if(band.length>=2){const top=band.map(s=>`${x(minsOf(s.slot))} ${y(s.hi)}`).join(" L"),bot=band.slice().reverse().map(s=>`${x(minsOf(s.slot))} ${y(s.lo)}`).join(" L");
    g+=`<path d="M${top} L${bot} Z" fill="rgba(120,144,168,.28)" stroke="none"/>`}
   band=[]};
  run.forEach(s=>{if(s.lo==null||s.hi==null){flushBand();return} band.push(s)});
  flushBand();
  const d=run.map((s,i)=>`${i?"L":"M"}${x(minsOf(s.slot))} ${y(s.median)}`).join(" ");
  g+=`<path d="${d}" fill="none" stroke="#6b7380" stroke-width="1.6" stroke-dasharray="6 5"/>`;
 });
 return g;
}
function chart(obs){const el=$("#chart"),W=1000,H=320,P={l:40,r:14,t:18,b:30};
 typicalNotes(obs);
 if(!obs.length){el.innerHTML='<p class="note">No readings in this range.</p>';return}
 if(range==="day"){dayChart(el,obs,W,H);return}
 const ok=obs.filter(o=>o.s==="ok"),t0=+obs[0].d,t1=Math.max(+obs[obs.length-1].d,t0+36e5),ym=Math.max(10,...ok.map(o=>o.c))*1.15;
 const x=t=>P.l+(t-t0)/(t1-t0)*(W-P.l-P.r),y=v=>H-P.b-v/ym*(H-P.t-P.b);let g="";
 for(let v=0;v<=ym;v+=ym>60?20:ym>30?10:5)g+=`<line x1="${P.l}" x2="${W-P.r}" y1="${y(v)}" y2="${y(v)}" stroke="#eee"/><text x="${P.l-6}" y="${y(v)+4}" text-anchor="end">${v}</text>`;
 const span=t1-t0,step=span>20*864e5?7*864e5:span>3*864e5?864e5:span>12*36e5?3*36e5:36e5;
 let tk=Math.ceil(t0/step)*step;if(step>=864e5){tk=+new Date(obs[0].p.date+"T00:00:00Z")}
 for(;tk<=t1;tk+=step){if(tk<t0)continue;g+=`<line x1="${x(tk)}" x2="${x(tk)}" y1="${P.t}" y2="${H-P.b}" stroke="#f1f1f1"/><text x="${x(tk)}" y="${H-10}" text-anchor="middle">${fmt(new Date(tk),step>=864e5?{day:"numeric",month:"short"}:{hour:"2-digit",minute:"2-digit"})}</text>`}
 for(let i=1;i<ok.length;i++){const a=ok[i-1],b=ok[i],gap=(b.d-a.d)/6e4;if(gap>6*60)continue;
  g+=`<line x1="${x(+a.d)}" y1="${y(a.c)}" x2="${x(+b.d)}" y2="${y(b.c)}" stroke="#7aa3d4" stroke-width="1.3" ${gap>25?'stroke-dasharray="4 4"':""}/>`}
 ok.forEach(o=>g+=`<circle cx="${x(+o.d)}" cy="${y(o.c)}" r="${ok.length>300?1.8:3.2}" fill="#2f6fb3"><title>${fmt(o.d,{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})}: ${o.c}</title></circle>`);
 obs.filter(o=>o.s!=="ok").forEach(o=>g+=`<text x="${x(+o.d)}" y="${H-P.b-4}" text-anchor="middle" fill="#b3261e" style="fill:#b3261e">×<title>${esc(o.s)} ${fmt(o.d,{hour:"2-digit",minute:"2-digit"})}</title></text>`);
 el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Observed counts">${g}</svg>`}
function dayChart(el,obs,W,H){
 const P={l:44,r:18,t:22,b:32},X0=6*60,X1=23*60;
 const typ=typicalOf(sel),ok=obs.filter(o=>o.s==="ok");
 const peak=Math.max(0,...ok.map(o=>o.c),...(typ?typ.slots.map(s=>Math.max(s.median,s.hi==null?0:s.hi)):[]));
 const ym=Math.max(50,Math.ceil(peak/10)*10);
 const x=m=>P.l+(m-X0)/(X1-X0)*(W-P.l-P.r),y=v=>H-P.b-(v/ym)*(H-P.t-P.b);let g="";
 for(let v=0;v<=ym;v+=10)g+=`<line x1="${P.l}" x2="${W-P.r}" y1="${y(v)}" y2="${y(v)}" stroke="#eee"/><text x="${P.l-6}" y="${y(v)+4}" text-anchor="end">${v}</text>`;
 for(let h=6;h<=22;h+=2)g+=`<line x1="${x(h*60)}" x2="${x(h*60)}" y1="${P.t}" y2="${H-P.b}" stroke="#f1f1f1"/><text x="${x(h*60)}" y="${H-8}" text-anchor="middle">${String(h).padStart(2,"0")}:00</text>`;
 g+=`<text x="${x(23*60)}" y="${H-8}" text-anchor="end">23:00</text>`;
 const latest=ok.length?ok[ok.length-1]:null;
 const latestMin=latest?latest.p.h*60+latest.p.m:null;
 const isToday=sel===parts(new Date()).date;
 g+=typicalLayer(typ,x,y);
 for(let i=1;i<ok.length;i++){const a=ok[i-1],b=ok[i],gap=(b.d-a.d)/6e4;if(gap>6*60)continue;
  g+=`<line x1="${x(a.p.h*60+a.p.m)}" y1="${y(a.c)}" x2="${x(b.p.h*60+b.p.m)}" y2="${y(b.c)}" stroke="#2f6fb3" stroke-width="2" ${gap>25?'stroke-dasharray="4 4"':""}/>`}
 ok.forEach(o=>g+=`<circle cx="${x(o.p.h*60+o.p.m)}" cy="${y(o.c)}" r="3.4" fill="#2f6fb3"><title>${fmt(o.d,{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})}: ${o.c}</title></circle>`);
 obs.filter(o=>o.s!=="ok").forEach(o=>g+=`<text x="${x(o.p.h*60+o.p.m)}" y="${H-P.b-4}" text-anchor="middle" fill="#b3261e" style="fill:#b3261e">×<title>${esc(o.s)} ${fmt(o.d,{hour:"2-digit",minute:"2-digit"})}</title></text>`);
 if(isToday&&latest){
  const mx=latestMin,hh=fmt(latest.d,{hour:"2-digit",minute:"2-digit"});
  g+=`<line x1="${x(mx)}" x2="${x(mx)}" y1="${P.t}" y2="${H-P.b}" stroke="#2f6fb3" stroke-dasharray="2 3" stroke-width="1.2"/>`;
  g+=`<text x="${x(mx)}" y="${P.t-6}" text-anchor="middle" fill="#2f6fb3">Latest · ${hh}</text>`;
  g+=`<g><rect x="${x(mx)+6}" y="${y(latest.c)-16}" width="30" height="18" rx="4" fill="#2f6fb3"/><text class="bubble-num" x="${x(mx)+21}" y="${y(latest.c)-3}" text-anchor="middle">${latest.c}</text></g>`;
 }
 el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Today versus the usual pattern">${g}</svg>`}
function compare(){const el=$("#compare"),ok=D.observations.filter(o=>o.s==="ok"),dates=[...new Set(ok.map(o=>o.p.date))].filter(d=>d<=sel).slice(-7);
 if(dates.length<2){el.innerHTML="";$("#compareNote").textContent="Needs readings from at least two dates.";return}
 const W=1000,H=280,P={l:40,r:110,t:10,b:28},ym=Math.max(10,...ok.map(o=>o.c))*1.15,x=m=>P.l+(m-360)/(1380-360)*(W-P.l-P.r),y=v=>H-P.b-v/ym*(H-P.t-P.b);
 const cols=["#c9d4e3","#b3c3da","#9ab0cf","#7f9cc4","#5f85b8","#3f6ea9","#1f4e8c"].slice(-dates.length);let g="";
 for(let h=6;h<=23;h+=2)g+=`<text x="${x(h*60)}" y="${H-8}" text-anchor="middle">${String(h).padStart(2,"0")}:00</text><line x1="${x(h*60)}" x2="${x(h*60)}" y1="${P.t}" y2="${H-P.b}" stroke="#f1f1f1"/>`;
 dates.forEach((ds,i)=>{const pts=ok.filter(o=>o.p.date===ds);let path="";pts.forEach((o,j)=>{const m=o.p.h*60+o.p.m,gap=j?(o.d-pts[j-1].d)/6e4:0;path+=(j&&gap<=25?"L":"M")+x(m)+" "+y(o.c)});
  const last=ds===sel;g+=`<path d="${path}" fill="none" stroke="${cols[i]}" stroke-width="${last?2.4:1.4}"/>`;
  g+=`<text x="${W-P.r+8}" y="${P.t+14+i*16}" style="fill:${cols[i]};font-weight:${last?700:400}">${fmt(pts[0].d,{weekday:"short",day:"numeric",month:"short"})}</text>`});
 el.innerHTML=`<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;$("#compareNote").textContent="Up to 7 most recent dates up to the selected date, by time of day. Lines broken where readings are > 25 min apart."}
function heat(){const ok=D.observations.filter(o=>o.s==="ok"&&o.p.h>=6&&o.p.h<23),cell={};
 ok.forEach(o=>{const k=o.p.wd+"-"+o.p.h;(cell[k]=cell[k]||{});(cell[k][o.p.date]=cell[k][o.p.date]||[]).push(o.c)});
 const stats={};Object.entries(cell).forEach(([k,byd])=>{const daily=Object.values(byd).map(median);stats[k]={med:median(daily),days:daily.length}});
 const mx=Math.max(1,...Object.values(stats).map(s=>s.med));let h="<table class='heat'><tr><th></th>"+Array.from({length:17},(_,i)=>`<th>${i+6}</th>`).join("")+"</tr>";
 DAYS.forEach((d,wd)=>{h+=`<tr><th>${d}</th>`;for(let hr=6;hr<23;hr++){const s=stats[wd+"-"+hr];
  if(!s){h+="<td style='background:#f3f4f6'></td>";continue}const a=.12+.78*s.med/mx;
  h+=`<td title="${d} ${hr}:00 median ${s.med} over ${s.days} date(s)" style="background:rgba(47,111,179,${a});color:${a>.55?"#fff":"#1d2430"}">${Math.round(s.med)}<small>${s.days}d</small></td>`}h+="</tr>"});
 $("#heat").innerHTML=h+"</table>";
 const q=Object.entries(stats).filter(([,s])=>s.days>=3).sort((a,b)=>a[1].med-b[1].med).slice(0,8);
 $("#quiet").innerHTML=q.length?"<h2 style='margin-top:12px'>Quietest observed hours (≥ 3 dates)</h2><ol>"+q.map(([k,s])=>{const[wd,hr]=k.split("-");return`<li>${DAYS[wd]} ${hr}:00 – median ${s.med} (${s.days} dates)</li>`}).join("")+"</ol>"
  :"<p class='note'><b>No quiet-slot ranking yet</b> — no weekday/hour has readings from 3 distinct dates.</p>"}
function expected(now){const c=D.cadence,start=new Date(c.hourly_from),sw=new Date(c.quarter_hour_from),cap=c.until?+new Date(c.until):Infinity,end=new Date(Math.min(+now,cap)),keys=[];
 for(let t=+start;t<=+end;t+=15*6e4){const d=new Date(t),p=parts(d);if(p.h<c.open_hour||p.h>=c.close_hour)continue;
  if(t<+sw){if(p.m===0)keys.push("h|"+p.date+" "+p.h)}else keys.push("q|"+p.date+" "+p.h+":"+Math.floor(p.m/15))}return keys}
function key(o){const sw=new Date(D.cadence.quarter_hour_from);return o.d<sw?"h|"+o.p.date+" "+o.p.h:"q|"+o.p.date+" "+o.p.h+":"+Math.floor(o.p.m/15)}
function coverage(){const exp=expected(new Date()),E=new Set(exp),ok=new Set(),fail=new Set();D.observations.forEach(o=>(o.s==="ok"?ok:fail).add(key(o)));
 const succ=[...ok].filter(k=>E.has(k)).length,f=[...fail].filter(k=>E.has(k)&&!ok.has(k)).length,miss=exp.length-succ-f;
 const byDate={};exp.forEach(k=>{const d=k.split("|")[1].slice(0,10);byDate[d]=byDate[d]||{e:0,s:0};byDate[d].e++;if(ok.has(k))byDate[d].s++});
 $("#coverage").innerHTML=`<p>Expected slots so far: <b>${exp.length}</b> · successful <b>${succ}</b> · failed <b>${f}</b> · missing <b>${miss}</b> · coverage <b>${exp.length?(100*succ/exp.length).toFixed(1):0}%</b></p>
 <p class="note">Schedule: hourly from 7 Nov 10:00 CET, every 15 min from 10:30 CET, 06:00–22:45 Europe/Vienna, daily. Collection has no end date. Missed slots stay empty.</p>
 <table><tr><th>Date</th><th>Expected</th><th>Successful</th><th>Coverage</th></tr>${Object.entries(byDate).reverse().map(([d,v])=>`<tr><td>${d}</td><td>${v.e}</td><td>${v.s}</td><td>${(100*v.s/v.e).toFixed(0)}%</td></tr>`).join("")}</table>`}
function table(obs){$("#tbl tbody").innerHTML=[...obs].reverse().map(o=>`<tr><td>${fmt(o.d,{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})} ${tzLabel(o.d)}</td><td>${o.c??"–"}</td><td>${esc(o.s)}</td></tr>`).join("")}
const FULL=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
function hhmmMins(s){const [h,m]=s.split(":").map(Number);return h*60+m}
function slotsLeftNow(h,m){const minutes=h*60+m,open=6*60,close=22*60+45,start=minutes<open?open:minutes-(minutes%15);return start>close?0:Math.floor((close-start)/15)+1}
function earliestNow(h,m){const minutes=h*60+m,first=8*60,lastStart=18*60+30,start=minutes<first?first:minutes-(minutes%15);if(start>lastStart)return null;return String(Math.floor(start/60)).padStart(2,"0")+":"+String(start%60).padStart(2,"0")}
function windowsOverlap(a,b){return Math.abs(hhmmMins(a.start)-hhmmMins(b.start))<90}
function bestSentence(prefix,w,basis){return prefix+": "+w.start+"–"+w.end+", typically ~"+w.shown+" people"+(basis?" ("+basis+")":"")}
function bestTimeBox(){const el=$("#bestTime");if(!el)return;
 if(!D||!D.best_time||!D.best_time.by_weekday){el.innerHTML="";return}
 const p=parts(new Date()),cat=D.best_time.by_weekday,today=FULL[p.wd],tomorrow=FULL[(p.wd+1)%7];
 const todayInfo=cat[today],tomInfo=cat[tomorrow];
 const tom=()=>{if(!tomInfo||!tomInfo.windows||!tomInfo.windows.length)return null;const w=tomInfo.windows[0];return {line:bestSentence("Tomorrow's quietest window",w,tomInfo.basis),confidence:tomInfo.basis.charAt(0).toUpperCase()+tomInfo.basis.slice(1)}};
 const earliest=earliestNow(p.h,p.m);
 if(!Object.keys(cat).length){el.innerHTML='<p class="fallback">No typical data yet</p>';return}
 if(earliest==null){const nxt=tom();el.innerHTML=`<h2>Best time today</h2><p class="fallback">No window left today</p>`+(nxt?`<p class="detail">${esc(nxt.line)}</p><p class="note">${esc(nxt.confidence)}</p>`:"");return}
 if(!todayInfo||!todayInfo.windows||!todayInfo.windows.length){el.innerHTML='<p class="fallback">No typical data yet</p>';return}
 const eligible=todayInfo.windows.filter(w=>w.start>=earliest);
 if(!eligible.length){const nxt=tom();el.innerHTML='<p class="fallback">No typical data for the rest of today</p>'+(nxt?`<p class="detail">${esc(nxt.line)}</p><p class="note">${esc(nxt.confidence)}</p>`:"");return}
 const best=eligible[0],runner=eligible.slice(1).find(w=>!windowsOverlap(best,w));
 const conf=todayInfo.basis.charAt(0).toUpperCase()+todayInfo.basis.slice(1);
 el.innerHTML=`<h2>Best time today</h2><p class="when">${esc(best.start)}–${esc(best.end)}</p><p class="detail">Quietest window left today, typically ~${best.shown} people</p><p class="note">${esc(conf)}</p>`+(runner?`<p class="runner">${esc(bestSentence("Runner-up",runner,null))}</p>`:"")}
function heroBlock(){const el=$("#hero");if(!el)return;const h=D.hero;
 if(!h||h.count==null){el.className="hero";el.innerHTML='<p class="hero-empty">No readings yet</p>';return}
 el.className="hero hero-"+h.band;
 const arrow={up:"↑",down:"↓",flat:"→"}[h.trend]||"";
 const meaning={up:"higher than the previous reading",down:"lower than the previous reading",flat:"same as the previous reading"}[h.trend]||"";
 const trend=arrow?`<span class="hero-trend" aria-label="${meaning}">${arrow}</span>`:"";
 const usual=h.usual&&h.usual.line?`<p class="hero-usual">${esc(h.usual.line)}</p>`:"";
 el.innerHTML=`<div class="hero-count"><span class="hero-num">${h.count}</span>${trend}</div><p class="hero-time">${esc(h.time_label)}</p>${usual}`}
function render(){if(!D)return;const obs=D.observations.filter(inRange);
 $("#rangeLabel").textContent={day:"Selected day",week:"Mon–Sun week containing date",month:"Calendar month of date",all:"All observations"}[range];
 heroBlock();bestTimeBox();status();kpis(obs);chart(obs);compare();heat();coverage();table(obs)}
document.querySelectorAll(".seg button").forEach(b=>b.onclick=()=>{document.querySelectorAll(".seg button").forEach(x=>x.classList.remove("on"));b.classList.add("on");range=b.dataset.r;render()});
$("#date").onchange=e=>{sel=e.target.value||sel;render()};
load();setInterval(()=>D&&bestTimeBox(),60000);
