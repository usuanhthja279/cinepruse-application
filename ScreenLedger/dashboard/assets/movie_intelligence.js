"use strict";

let ROOT = "data/district_hourly_runs_2026-11-07/";
let snapshotDate = "2026-11-07";
const $ = id => document.getElementById(id);
const app = { summaries: null, comparisons: [], mapping: [], coverage: [], provenance: null, geo: null, sessionsByRun: {}, sessionPage: 0 };
const number = value => Number(value || 0).toLocaleString("en-IN");
const money = value => value == null || value === "" ? "Unavailable" : `₹${(Number(value) / 1e7).toFixed(2)} crore`;
const pct = value => `${(Number(value) * 100).toFixed(1)}%`;
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const csvRows = text => {
  const lines = text.trim().split(/\r?\n/), parse = line => {
    const cells = []; let cell = "", quoted = false;
    for (let i=0;i<line.length;i++) { const c=line[i]; if(c==='"'&&line[i+1]==='"'&&quoted){cell+='"';i++;} else if(c==='"') quoted=!quoted; else if(c===','&&!quoted){cells.push(cell);cell="";} else cell+=c; }
    cells.push(cell); return cells;
  };
  const head=parse(lines.shift()); return lines.map(line=>Object.fromEntries(parse(line).map((v,i)=>[head[i],v])));
};
const tile = (label, value, note, accent=false, flag="") => `<div class="metric"><div class="over">${esc(label)}</div><div class="number ${accent?'em':''}">${esc(value)}</div><div class="sub">${esc(note)}</div>${flag?`<div class="flag">${esc(flag)}</div>`:""}</div>`;
const runs = () => app.summaries.runs;
const selected = () => runs()[Math.max(0, Number($("runSelect").value))];

function render() {
  if (!app.summaries) return;
  const run=selected(), runIndex=Math.max(0,Number($("runSelect").value)), comparison=app.comparisons[runIndex-1], c=comparison?.comparison;
  const total=run.target_city_feeds, cap=run.captured_city_feeds;
  $("overviewMetrics").innerHTML = tile("Booked + blocked seats",number(run.booked_plus_blocked_seats),"Per owner-confirmed revenue basis",true)+tile("Confirmed revenue",money(run.confirmed_revenue_inr),"Payment confirmation supplied by project owner")+tile("Unique screenings",number(run.unique_session_count),"Deduplicated session records")+tile("Feed coverage",`${number(cap)} / ${number(total)}`,`${number(run.failed_city_feeds)} failed · ${number(run.not_collected_this_hour_city_feeds)} not collected`);
  $("deltaMetrics").innerHTML = c?tile("Matched future sessions",number(c.matched_future_session_count),`${c.previous_hour_ist} → ${c.current_hour_ist} IST`)+tile("Tickets sold · matched shows",`+${number(c.seat_change.positive_booked_plus_blocked_seats)}`,"Booked + blocked seat increases",true)+tile("Released / corrected seats",`−${number(c.seat_change.released_or_corrected_seats)}`,"Shown separately from increases")+tile("Net matched seat change",`${c.seat_change.net_booked_plus_blocked_seat_change>=0?"+":""}${number(c.seat_change.net_booked_plus_blocked_seat_change)}`,`${number(c.new_session_count)} new sessions; ${number(c.disappeared_session_count)} disappeared`):tile("Hourly comparison","Not available","The first snapshot has no previous run.")+tile("Tickets sold · matched shows","—","Requires a preceding capture")+tile("Released / corrected seats","—","Requires a preceding capture")+tile("Net matched seat change","—","Requires a preceding capture");
  $("coverageTitle").textContent=pct(cap/total);$("coverageFill").style.width=pct(cap/total);$("captured").textContent=`${number(cap)} / ${number(total)}`;$("missing").textContent=number(run.not_collected_this_hour_city_feeds);$("failed").textContent=number(run.failed_city_feeds);
  $("movieMetrics").innerHTML=tile("Booked + blocked seats",number(run.booked_plus_blocked_seats),"Current captured snapshot",true)+tile("Confirmed revenue",money(run.confirmed_revenue_inr),"Per owner payment confirmation")+tile("Total seats",number(run.total_seats),"Across deduplicated screenings")+tile("Unique shows",number(run.unique_session_count),"Coverage-dependent count");
  const ratio=run.total_seats?run.booked_plus_blocked_seats/run.total_seats:0;$("occupancyFill").style.width=pct(ratio);$("bookedLabel").textContent=`${number(run.booked_plus_blocked_seats)} booked + blocked`;$("availableLabel").textContent=`${number(run.available_seats)} available`;$("snapshotTime").textContent=`${run.collection_hour_ist} IST · ${run.service_date_ist}`;
  $("healthMetrics").innerHTML=tile("Captured feeds",number(cap),`of ${number(total)} targets`,true)+tile("Not collected",number(run.not_collected_this_hour_city_feeds),"Unknown coverage, not zero shows")+tile("Failed feeds",number(run.failed_city_feeds),"Failures are separate from empty show lists")+tile("Duplicate feed rows",number(run.duplicate_city_feed_rows),"Removed from unique session count");
  $("healthRows").innerHTML=runs().map(r=>`<tr><td>${esc(r.collection_hour_ist)}</td><td>${number(r.captured_city_feeds)}</td><td>${pct(r.captured_city_feeds/r.target_city_feeds)}</td><td>${number(r.failed_city_feeds)}</td><td>${number(r.not_collected_this_hour_city_feeds)}</td><td>${number(r.unique_session_count)}</td></tr>`).join("");
  $("hourRows").innerHTML=runs().map(r=>`<tr><td>${esc(r.collection_hour_ist)} IST</td><td>${number(r.unique_session_count)}</td><td>${number(r.booked_plus_blocked_seats)}</td><td>${money(r.confirmed_revenue_inr)}</td><td>${number(r.captured_city_feeds)} / ${number(r.target_city_feeds)}</td></tr>`).join("");
  if(c){const rev=c.confirmed_revenue_change_inr;$("comparisonNote").textContent=`${number(c.matched_future_session_count)} shows matched on venue, showtime and capacity over ${c.capture_interval_minutes.min}–${c.capture_interval_minutes.max} minutes. ${number(c.new_session_count)} new and ${number(c.disappeared_session_count)} disappeared shows are kept out of the sold-ticket change. Confirmed revenue change is unavailable because ${number(rev.incomplete_pricing_session_count)} matched shows have incomplete pricing.`;}else{$("comparisonNote").textContent="This is the first saved snapshot. Ticket-change comparisons begin with the next hourly capture.";}
  const available=app.comparisons.filter(Boolean),max=Math.max(1,...available.flatMap(x=>[x.comparison.seat_change.positive_booked_plus_blocked_seats,x.comparison.seat_change.released_or_corrected_seats]));
  $("bars").innerHTML=available.map(envelope=>{const c=envelope.comparison;const width=Math.max(18,Math.floor(100/available.length)-5);return `<div class="bar-item" style="width:${width}%;flex-shrink:0"><div class="column a" style="height:${Math.max(5,c.seat_change.positive_booked_plus_blocked_seats/max*170)}px"><span>+${number(c.seat_change.positive_booked_plus_blocked_seats)}</span></div><div class="column b" style="height:${Math.max(5,c.seat_change.released_or_corrected_seats/max*170)}px"><span>−${number(c.seat_change.released_or_corrected_seats)}</span></div></div>`;}).join("")||'<div class="empty">Hourly matched comparisons are not available yet.</div>';
  $("barLabels").innerHTML=available.map(x=>`<span>${esc(x.comparison.previous_hour_ist)} → ${esc(x.comparison.current_hour_ist)}</span>`).join("");
  renderSessions();
}

function navigate(view) {
  document.querySelectorAll(".view").forEach(node=>node.classList.toggle("active",node.id===view));
  document.querySelectorAll(".nav").forEach(node=>node.classList.toggle("active",node.dataset.view===view));
  $("breadcrumb").textContent=({overview:"Overview",movie:"Movie analytics",geo:"India explorer",health:"Collector health"})[view];
  if(view==="geo") loadMap(); if(view==="movie") loadSessions(); window.scrollTo({top:0,behavior:"smooth"});
}
document.querySelectorAll("[data-view]").forEach(node=>node.addEventListener("click",()=>navigate(node.dataset.view)));
document.querySelectorAll("[data-go]").forEach(node=>node.addEventListener("click",()=>navigate(node.dataset.go)));
$("runSelect").addEventListener("change",()=>{app.sessionPage=0;render();loadCoverageForSelected();if($("movie").classList.contains("active"))loadSessions();});
async function loadCoverageForSelected(){if(!app.summaries)return;const run=selected();const hour=run.collection_hour_ist.replace(":","");try{const response=await fetch(`${ROOT}city_coverage_${snapshotDate}_${hour}_IST.csv?refresh=${Date.now()}`);if(response.ok)app.coverage=csvRows(await response.text());}catch{} }

function renderMovies(){const q=$("movieSearch").value.trim().toLowerCase();const match="ramayana 176276".includes(q);$("movieListing").innerHTML=match?`<div class="movie-card"><div class="poster">RAMAYANA</div><div style="min-width:0;flex:1"><div class="eyebrow">District capture</div><h2>Ramayana</h2><p class="muted">Movie ID 176276 · November 7, 2026</p><button class="btn primary" data-go="movie">Explore movie →</button></div></div>`:`<div class="empty">No saved movie matches your search. Only movies present in saved capture data appear here.</div>`;document.querySelectorAll("#movieListing [data-go]").forEach(node=>node.addEventListener("click",()=>navigate(node.dataset.go)));}
$("movieSearch").addEventListener("input",renderMovies);

async function loadSessions(){
 if(!app.summaries)return;const index=Math.max(0,Number($("runSelect").value));if(app.sessionsByRun[index]){renderSessions();return;}
 $("sessionCount").textContent="Loading…";const hour=runs()[index].collection_hour_ist.replace(":","");
 try{const response=await fetch(`${ROOT}unique_screenings_${snapshotDate}_${hour}_IST.csv?refresh=${Date.now()}`);if(!response.ok)throw new Error("Saved screening export unavailable");app.sessionsByRun[index]=csvRows(await response.text());app.sessionPage=0;renderSessions();}
 catch(error){$("sessionCount").textContent="Unavailable";$("sessionRows").innerHTML=`<tr><td colspan="9">${esc(error.message)}</td></tr>`;}
}
function renderSessions(){
 if(!$("sessionRows"))return;const index=Math.max(0,Number($("runSelect").value)),rows=app.sessionsByRun[index];if(!rows){$("sessionCount").textContent="Not loaded";return;}
 const query=$("sessionSearch").value.trim().toLowerCase();const filtered=query?rows.filter(r=>[r.cinema_name,r.actual_city,r.source_city_slug,r.show_datetime_ist].some(v=>String(v||"").toLowerCase().includes(query))):rows;
 const pageSize=100,pageCount=Math.max(1,Math.ceil(filtered.length/pageSize));app.sessionPage=Math.max(0,Math.min(app.sessionPage,pageCount-1));const start=app.sessionPage*pageSize,visible=filtered.slice(start,start+pageSize);
 $("sessionCount").textContent=`${number(filtered.length)} sessions`;$("sessionRows").innerHTML=visible.length?visible.map(r=>`<tr><td>${esc(r.show_datetime_ist)}</td><td>${esc(r.cinema_name)}</td><td>${esc(r.actual_city)}</td><td>${esc(r.source_city_slug)}</td><td>${number(r.total_seats)}</td><td>${number(r.available_seats)}</td><td>${number(r.booked_plus_blocked_seats)}</td><td>${money(r.confirmed_revenue_inr)}</td><td>${String(r.pricing_complete).toLowerCase()==="true"?"Complete":"Incomplete"}</td></tr>`).join(""):'<tr><td colspan="9">No sessions match this filter.</td></tr>';
 $("sessionPageSummary").textContent=filtered.length?`Showing ${number(start+1)}–${number(Math.min(start+pageSize,filtered.length))} of ${number(filtered.length)} · page ${app.sessionPage+1} of ${pageCount}`:"No matching rows";$("sessionPrev").disabled=app.sessionPage===0;$("sessionNext").disabled=app.sessionPage>=pageCount-1;
}
$("sessionSearch").addEventListener("input",()=>{app.sessionPage=0;renderSessions();});$("sessionPrev").addEventListener("click",()=>{app.sessionPage--;renderSessions();});$("sessionNext").addEventListener("click",()=>{app.sessionPage++;renderSessions();});

const norm = value => String(value||"").normalize("NFKD").replace(/[\u0300-\u036f]/g,"").toLowerCase().replace(/&/g,"and").replace(/[^a-z0-9]+/g," ").trim();
const stateKey = value => {let key=norm(value);if(key.includes("andaman nicobar"))return "andaman and nicobar islands";if(key.includes("arunanchal")||key.includes("arunachal"))return "arunachal pradesh";if(key.includes("dadra")&&key.includes("daman"))return "dadra and nagar haveli and daman and diu";return key;};
function cityRowsForState(state){return app.mapping.filter(r=>r.mapping_status==="matched_exact_2011_location_name"&&stateKey(r.state_or_ut)===stateKey(state));}
function coverageForCity(row){const key=norm(row.display_label),slug=norm(row.display_label).replace(/\s+/g,"-");return app.coverage.find(c=>norm(c.display_name)===key||norm(c.city_slug)===norm(slug));}
function openState(state){$("modalTitle").textContent=state;const cities=cityRowsForState(state);const counts={captured:0,failed:0,not:0};for(const row of cities){const c=coverageForCity(row);if(c?.capture_status==="captured")counts.captured++;else if(c?.capture_status==="failed")counts.failed++;else counts.not++;}
  $("modalCities").innerHTML=cities.length?cities.map(row=>{const c=coverageForCity(row),status=c?.capture_status||"not mapped in this run";return `<div class="cityitem"><strong>${esc(row.display_label)}</strong><small>${esc(status)}${c?.show_count?` · ${number(c.show_count)} feed rows`:""}</small></div>`}).join(""):`<div class="empty" style="grid-column:1/-1">No unambiguous Census town-name matches in this selector snapshot.</div>`;
  $("cityMessage").textContent=`Selector-label coverage only: ${number(cities.length)} mapped labels, ${number(counts.captured)} captured, ${number(counts.failed)} failed, ${number(counts.not)} not captured or not matched. These labels do not locate individual cinemas; state bookings, occupancy and revenue are not assigned.`;
  $("stateModal").classList.add("open");$("closeModal").focus();document.querySelectorAll("#indiaMap path").forEach(path=>path.classList.toggle("selected",path.dataset.name===state));
}
function loadMap(){if(app.geo)return;fetch("assets/india_state_map_simplified.geojson").then(r=>{if(!r.ok)throw new Error("Map asset could not be loaded");return r.json()}).then(geo=>{app.geo=geo;drawMap();}).catch(e=>{$("geoStatus").textContent=`Map unavailable: ${e.message}`;});}
function drawMap(){
 const svg=$("indiaMap"),NS="http://www.w3.org/2000/svg",bounds=[67.3,6.0,98.2,38.0],scale=Math.min(638/(bounds[2]-bounds[0]),620/(bounds[3]-bounds[1]));
 const project=p=>[350+(p[0]-(bounds[0]+bounds[2])/2)*scale,335-(p[1]-(bounds[1]+bounds[3])/2)*scale];
 const ring=r=>r.map((pt,i)=>{const [x,y]=project(pt);return `${i?"L":"M"}${x.toFixed(1)},${y.toFixed(1)}`}).join(" ")+" Z";
 const pathFor=g=>(g.type==="Polygon"?[g.coordinates]:g.coordinates).map(poly=>poly.map(ring).join(" ")).join(" ");
 for(const feature of app.geo.features){const name=feature.properties.name,path=document.createElementNS(NS,"path");path.setAttribute("d",pathFor(feature.geometry));path.setAttribute("fill-rule","evenodd");path.setAttribute("tabindex","0");path.setAttribute("aria-label",`Open ${name} coverage details`);path.dataset.name=name;path.addEventListener("click",()=>openState(name));path.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openState(name);}});path.addEventListener("mouseenter",()=>{$("mapTooltip").style.display="block";$("mapTooltip").textContent=`${name} · feed coverage only; cinema-level state totals unavailable`;});path.addEventListener("mouseleave",()=>$("mapTooltip").style.display="none");svg.appendChild(path);}
 renderStates(); $("geoStatus").textContent="Simplified state and union-territory geometry loaded from the package display asset. Political-border authenticity has not been independently certified.";
}
function renderStates(){if(!app.geo)return;const query=$("stateSearch").value.toLowerCase();const names=app.geo.features.map(f=>f.properties.name).sort((a,b)=>a.localeCompare(b));$("stateResults").innerHTML=names.filter(name=>name.toLowerCase().includes(query)).map(name=>`<button class="regionlink" data-state="${esc(name)}">${esc(name)} <small>Open selector-feed coverage</small></button>`).join("")||'<div class="empty">No state found.</div>';document.querySelectorAll("[data-state]").forEach(node=>node.addEventListener("click",()=>openState(node.dataset.state)));}
$("stateSearch").addEventListener("input",renderStates);$("closeModal").addEventListener("click",()=>$("stateModal").classList.remove("open"));$("stateModal").addEventListener("click",event=>{if(event.target===$("stateModal"))$("stateModal").classList.remove("open")});document.addEventListener("keydown",event=>{if(event.key==="Escape")$("stateModal").classList.remove("open")});

let loadedSnapshotVersion = "";
let snapshotRefreshRunning = false;
async function init(){
 try{
  if(snapshotRefreshRunning)return;snapshotRefreshRunning=true;
  const manifestResponse=await fetch(`data/district_hourly_runs_latest.json?refresh=${Date.now()}`,{cache:"no-store"});
  let nextVersion="";
  if(manifestResponse.ok){const manifest=await manifestResponse.json();nextVersion=`${manifest.service_date_ist}|${manifest.generated_at_ist}`;if(nextVersion===loadedSnapshotVersion)return;ROOT=`${manifest.directory.replace(/\\/g,"/").replace(/\/$/,"")}/`;snapshotDate=manifest.service_date_ist;}
  const summaryResponse=await fetch(`${ROOT}run_summaries.json?refresh=${Date.now()}`,{cache:"no-store"});
  if(!summaryResponse.ok)throw new Error("Published hourly data is unavailable");
  const summary=await summaryResponse.json();
  if(nextVersion)loadedSnapshotVersion=nextVersion;
  const [delta,mapping,coverage,provenance]=await Promise.all([
   Promise.all((summary.comparisons||[]).map(file=>fetch(`${ROOT}${file}?refresh=${Date.now()}`,{cache:"no-store"}).then(r=>r.ok?r.json():null).catch(()=>null))),
   fetch("data/city_state_mapping_2026-11-07.csv").then(r=>r.text()),
   summary.runs.length?fetch(`${ROOT}city_coverage_${snapshotDate}_${summary.runs[summary.runs.length-1].collection_hour_ist.replace(":","")}_IST.csv?refresh=${Date.now()}`).then(r=>r.text()):Promise.resolve(""),
   fetch("data/city_state_mapping_2026-11-07.provenance.json").then(r=>r.json())
  ]);
  app.summaries=summary;app.comparisons=[null,...delta];app.mapping=csvRows(mapping);app.coverage=coverage?csvRows(coverage):[];app.provenance=provenance;app.sessionsByRun={};
  if(!summary.runs.length)throw new Error("No completed hourly captures are available yet");
  $("dateTag").textContent=new Date(`${snapshotDate}T00:00:00`).toLocaleDateString("en-IN",{day:"2-digit",month:"short",year:"numeric"});
  $("runSelect").innerHTML=summary.runs.map((r,i)=>`<option value="${i}">${esc(r.collection_hour_ist)} IST snapshot</option>`).join("");$("runSelect").value=String(summary.runs.length-1);
  render();renderMovies();
  const statuses=provenance.status_counts||{};const mapped=(statuses.matched_exact_2011_town_name||0)+(statuses.matched_exact_2011_settlement_name||0)+(statuses.matched_curated_city_state||0);$("mappingCoverage").textContent=`City-selector state reference: ${number(mapped)} of ${number(provenance.selector_labels)} labels assigned; ${number(statuses.ambiguous_multiple_states||0)} ambiguous and ${number(statuses.unmatched||0)} unmatched. Not a cinema-to-state map.`;
  $("liveStatus").textContent=`Auto-updating · latest completed capture published ${summary.generated_at_ist||"just now"} IST`;
  document.querySelector(".load-error")?.remove();
 }catch(error){if(!document.querySelector(".load-error")){const notice=document.createElement("div");notice.className="notice load-error";notice.textContent=`Saved data could not be loaded. ${error.message}`;document.body.prepend(notice);}}
 finally{snapshotRefreshRunning=false;}
}
init();
setInterval(init,300000);
