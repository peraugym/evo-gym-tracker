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
function chart(obs){const el=$("#chart"),W=1000,H=320,P={l:40,r:14,t:12,b:30};
 if(!obs.length){el.innerHTML='<p class="note">No readings in this range.</p>';return}
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
 heroBlock();status();kpis(obs);chart(obs);compare();heat();coverage();table(obs)}
document.querySelectorAll(".seg button").forEach(b=>b.onclick=()=>{document.querySelectorAll(".seg button").forEach(x=>x.classList.remove("on"));b.classList.add("on");range=b.dataset.r;render()});
$("#date").onchange=e=>{sel=e.target.value||sel;render()};
load();
