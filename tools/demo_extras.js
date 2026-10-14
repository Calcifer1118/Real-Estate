/* ---------- calculator: cycle the Pag-IBIG terms until the visitor taps ---------- */
let cycT=0;
function autoCycle(){
  clearInterval(cycT); if(reduce) return;
  const body=$("#compBody"); if(!body) return;
  let user=false;
  body.addEventListener("pointerdown",()=>{ user=true; clearInterval(cycT); const n=$("#autonote"); if(n) n.remove(); },{ once:true });
  const seg=()=>body.querySelector(".seg:not([hidden]) , #finPagibig:not([hidden]) .seg, #finBank:not([hidden]) .seg");
  const tick=()=>{ if(user) return; const pane=body.querySelector("#finPagibig:not([hidden]), #finBank:not([hidden])"); const sg=pane&&pane.querySelector(".seg"); if(!sg) return;
    const btns=[...sg.querySelectorAll("button")], i=btns.findIndex(b=>b.getAttribute("aria-pressed")==="true"); btns[(i+1)%btns.length].onclick(); };
  const ma=body.querySelector(".ma"); if(ma && !$("#autonote")) ma.insertAdjacentHTML("afterend",'<span class="autonote" id="autonote"><i></i>Showing each term · tap one to stop</span>');
  const start=()=>{ clearInterval(cycT); cycT=setInterval(tick,2200); };
  const io2=new IntersectionObserver(es=>{ if(es.some(e=>e.isIntersecting)){ io2.disconnect(); start(); } },{ threshold:.3 }); io2.observe(body);
}

/* ---------- booking form ---------- */
const SLOTS=["8:00 AM","9:00 AM","10:00 AM","11:00 AM","1:00 PM","2:00 PM","3:00 PM","4:00 PM"];
function bookForm(P){
  const d=new Date(); d.setDate(d.getDate()+((6-d.getDay()+7)%7||7));
  const iso=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  return `<form id="leadForm" autocomplete="on">
    <div class="two"><label for="fName">Full name<input id="fName" required autocomplete="name" placeholder="Juan dela Cruz"></label>
    <label for="fMobile">Mobile number<input id="fMobile" required inputmode="tel" autocomplete="tel" placeholder="0917 123 4567"></label></div>
    <div class="two"><label for="fProj">Project<select id="fProj">${PROJECTS.map(x=>`<option${x===P?" selected":""}>${x.brand} ${x.name}</option>`).join("")}</select></label>
    <label for="fDay">Preferred day<input id="fDay" type="date" required value="${iso}"></label></div>
    <label>Preferred time<div class="times" id="fTimes" role="group" aria-label="Preferred time">${SLOTS.map(t=>`<button type="button" aria-pressed="${t==="10:00 AM"}">${t}</button>`).join("")}</div></label>
    <button class="btn" type="submit">${cal}Book my free tripping</button>
    <p class="fine">Free, no obligation. Your details go only to ${SELLER.name}.</p>
  </form>`;
}
function wireBook(){
  const f=$("#leadForm"); if(!f) return;
  const times=[...f.querySelectorAll("#fTimes button")];
  times.forEach(b=>b.onclick=()=>times.forEach(x=>x.setAttribute("aria-pressed",x===b)));
  f.onsubmit=e=>{ e.preventDefault();
    const name=$("#fName").value.trim()||"Client", first=name.split(" ")[0];
    const time=(times.find(b=>b.getAttribute("aria-pressed")==="true")||times[2]).textContent;
    const day=$("#fDay").value ? new Date($("#fDay").value+"T00:00").toLocaleDateString("en-PH",{weekday:"short",month:"short",day:"numeric"}) : "Any day";
    const lead={ type:"lead", name, mobile:$("#fMobile").value, project:$("#fProj").value, day, time, agent:SELLER.name };
    try{ if(window.parent!==window) parent.postMessage(lead,"*"); }catch(_){}
    let root=$("#sent"); if(!root){ root=document.createElement("div"); root.id="sent"; root.className="sent"; document.body.appendChild(root); }
    root.innerHTML=`<div class="sheet"><span class="eyebrow">Request sent</span><h3>Thanks, ${first.replace(/[<>&"]/g,"")}!</h3>
      <p class="fine" style="font-size:15px">${SELLER.name} got your request for ${day}, ${time}. Tap below to confirm in Messenger; your details are ready to send.</p>
      <a class="btn fb" href="${msg("book",CUR)}" target="_blank" rel="noopener">Continue in Messenger</a><button class="x" type="button">Back to the site</button></div>`;
    root.querySelector(".x").onclick=()=>root.classList.remove("on");
    requestAnimationFrame(()=>requestAnimationFrame(()=>root.classList.add("on")));
  };
}
document.addEventListener("click",e=>{ const a=e.target.closest&&e.target.closest("[data-jump]"); if(!a) return; e.preventDefault(); const t=document.getElementById(a.dataset.jump); if(t) t.scrollIntoView({behavior:reduce?"auto":"smooth"}); });

/* ---------- when shown inside the proposal's phone ---------- */
const EMBED = window.parent!==window;
if(EMBED) document.documentElement.classList.add("embedded");
addEventListener("message",e=>{ const m=e.data||{};
  if(m.type==="jump"){ const t=m.to==="top"?null:document.getElementById(m.to); if(m.to==="top") scrollTo({top:0,behavior:reduce?"auto":"smooth"}); else if(t) t.scrollIntoView({behavior:reduce?"auto":"smooth"}); }
  if(m.type==="agent"){ SELLER.name=m.name; $("#sellerName").textContent=m.name; }
  if(m.type==="chat") openChat();
});
const SECS=["location","models","finished","amenities","compute","tcp","book"];
let lastSec="";
addEventListener("scroll",()=>{ if(!EMBED) return; let cur="top";
  SECS.forEach(id=>{ const el=document.getElementById(id); if(el && el.getBoundingClientRect().top<innerHeight*0.45) cur=id; });
  if(cur!==lastSec){ lastSec=cur; try{ parent.postMessage({type:"section",id:cur},"*"); }catch(_){} } },{passive:true});

function bookLinks(P, modelId){
  ["#msgBtn","#stickyBtn"].forEach(s=>{ const a=$(s);
    if(P && $("#leadForm")){ a.href="#book"; a.dataset.jump="book"; a.removeAttribute("target"); }
    else { a.href=msg("book",CUR,modelId); delete a.dataset.jump; a.target="_blank"; } });
}

/* ---------- AI assistant: sample conversation (optional add-on) ---------- */
const CHAT=[
  ["u","Hi! Magkano po monthly ng Calista Mid sa Gen Tri?"],
  ["a","Hi po! 😊 Sample from the official Calista Mid computation sheet at PHirst Impressions Gen Tri:<br>• <b>Downpayment:</b> 10%, spread over 12 months (₱12,872.91 a month on the sample unit)<br>• <b>After that, Pag-IBIG over 20 years:</b> about <b>₱20,323.82 a month</b><br>Gusto n'yo po i-compare sa bank loan or shorter term?"],
  ["u","Ano po kasama sa TCP? May hidden charges ba?"],
  ["a","Wala pong hidden charges. Kasama na sa total contract price ang bank charges, title transfer fee, move-in fees, electricity & water installation fees, at processing fee."],
  ["u","Pwede po mag-tripping this Saturday?"],
  ["a","Yes po! Free ang tripping, any day 8 AM–5 PM. Anong oras po kayo available? Pakibigay na rin po ng name at mobile number para ma-confirm namin."],
  ["u","10 AM po. Maria Santos, 0917 555 0123"],
  ["a",()=>`Salamat, Maria! ✅ Naka-book na po kayo: <b>Saturday, 10:00 AM</b> sa PHirst Impressions Gen Tri. ${SELLER.name} will message you on Messenger to confirm. See you po!`]
];
let chatRun=0;
function chatUI(){
  if($("#aiBubble")) return;
  document.body.insertAdjacentHTML("beforeend",`
  <button id="aiBubble" type="button" aria-label="Chat with our assistant" aria-expanded="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z"/><path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01"/></svg><span>Ask us</span></button>
  <section id="aiChat" hidden aria-label="Assistant chat">
    <header><span class="aiav"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3v3M5 9h14v9a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z"/><circle cx="9.5" cy="13.5" r="1"/><circle cx="14.5" cy="13.5" r="1"/></svg></span><div><b>Team HML Assistant</b><small>Replies in seconds · 24/7</small></div><button type="button" class="aix" aria-label="Close chat">✕</button></header>
    <div class="aisample">Sample conversation · optional AI add-on</div>
    <div class="ailog" id="aiLog" aria-live="polite"></div>
    <div class="aiin"><input id="aiInput" placeholder="Type a message…" disabled><button type="button" disabled aria-label="Send">➤</button></div>
  </section>`);
  $("#aiBubble").onclick=()=>$("#aiChat").hidden?openChat():closeChat();
  $("#aiChat .aix").onclick=closeChat;
}
function closeChat(){ $("#aiChat").hidden=true; $("#aiBubble").setAttribute("aria-expanded","false"); }
function openChat(){
  chatUI(); const box=$("#aiChat"), log=$("#aiLog"); box.hidden=false; $("#aiBubble").setAttribute("aria-expanded","true");
  const run=++chatRun; log.innerHTML="";
  const add=(who,html)=>{ log.insertAdjacentHTML("beforeend",`<div class="aim ${who}">${html}</div>`); log.scrollTop=log.scrollHeight; };
  let i=0;
  const next=()=>{ if(run!==chatRun || box.hidden) return; if(i>=CHAT.length){
      add("note","📩 Lead sent to "+SELLER.name+" on Telegram and saved to the Google Sheet");
      try{ if(window.parent!==window) parent.postMessage({ type:"lead", name:"Maria Santos", mobile:"0917 555 0123", project:"PHirst Impressions Gen Tri", day:"Sat", time:"10:00 AM", agent:SELLER.name },"*"); }catch(_){}
      return; }
    const [who,txt]=CHAT[i++], html=typeof txt==="function"?txt():txt;
    if(who==="a" && !reduce){ add("a typing",'<i></i><i></i><i></i>'); setTimeout(()=>{ if(run!==chatRun) return; log.querySelector(".typing")?.remove(); add("a",html); setTimeout(next,1500); },1100); }
    else { add(who,html); setTimeout(next, reduce?0:(who==="u"?700:1500)); }
  };
  setTimeout(next, reduce?0:400);
}
chatUI();
