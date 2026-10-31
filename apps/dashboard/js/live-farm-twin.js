/* Aqua OS Live Farm Digital Twin
 * Visual-only simulator until commissioned sensor/actuator feedback is connected.
 * No physical commands are sent from this module.
 */
(() => {
  "use strict";
  const canvas = document.getElementById("aquaFarmTwinCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const tanks = Array.from({length:4},(_,i)=>({
    id:i+1, name:"Tank 0"+(i+1), do:5.65+i*.09, temp:28.7+i*.16, ph:7.9+i*.025, sal:18+i*.4,
    fans:[true,true,true,true], phase:i*.9, selected:i===0
  }));
  const reservoir={name:"Reservoir",level:0.72,phase:1.4};
  const state={selected:0,night:(new Date().getHours()<6||new Date().getHours()>=18),feeding:false,feedUntil:0,paused:false,zoom:1,orbit:0,drag:null,last:0,raf:0};
  let width=0,height=0,dpr=1,simTime=0;
  const $=id=>document.getElementById(id);
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const rnd=(seed)=>{const x=Math.sin(seed*127.1+311.7)*43758.5453;return x-Math.floor(x);};
  function resize(){const r=canvas.getBoundingClientRect();dpr=Math.min(window.devicePixelRatio||1,2);width=Math.max(1,r.width);height=Math.max(1,r.height);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);}
  function tankCenter(i){return {x:width*(.49-i*.065),y:height*(.30+i*.145)};}
  function poly(points,fill,stroke,line=1){ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=line;ctx.stroke();}}
  function drawRotor(x,y,r,on,angle){ctx.save();ctx.translate(x,y);ctx.fillStyle="#102a32";ctx.beginPath();ctx.ellipse(0,5,r*1.12,r*.42,0,0,Math.PI*2);ctx.fill();ctx.fillStyle="#263f43";ctx.fillRect(-r*.12,-r*.25,r*.24,r*.9);ctx.rotate(angle);ctx.strokeStyle=on?"#f8d58b":"#78939a";ctx.lineWidth=2;ctx.fillStyle=on?"#eab85d":"#738b91";for(let k=0;k<8;k++){ctx.rotate(Math.PI/4);ctx.beginPath();ctx.roundRect(-r*.12,-r*.96,r*.24,r*.58,2);ctx.fill();ctx.stroke();}ctx.beginPath();ctx.arc(0,0,r*.22,0,Math.PI*2);ctx.fillStyle="#f5e2b4";ctx.fill();ctx.restore();}
  function tankShape(i){const c=tankCenter(i);const w=Math.min(width*.285,300)*state.zoom,h=Math.min(height*.115,100)*state.zoom;const angle=-.50+state.orbit;const ux=Math.cos(angle),uy=Math.sin(angle),vx=-Math.sin(angle),vy=Math.cos(angle);const pt=(a,b)=>({x:c.x+ux*a*w/2+vx*b*h/2,y:c.y+uy*a*w/2+vy*b*h/2});return {c,w,h,pt,corners:[pt(-1,-1),pt(1,-1),pt(1,1),pt(-1,1)]};}
  function drawWater(i,t){const tank=tankShape(i),p=tank.corners;ctx.save();poly(p,"#0a2832","#416d76",4);const inset=p.map((_,k)=>{const center={x:p.reduce((s,v)=>s+v.x,0)/4,y:p.reduce((s,v)=>s+v.y,0)/4};return {x:center.x+(p[k].x-center.x)*.91,y:center.y+(p[k].y-center.y)*.84};});poly(inset,"#07566a","#278b98",1.5);
    ctx.save();ctx.beginPath();inset.forEach((v,k)=>k?ctx.lineTo(v.x,v.y):ctx.moveTo(v.x,v.y));ctx.closePath();ctx.clip();
    const grad=ctx.createLinearGradient(tank.c.x,tank.c.y-tank.h,tank.c.x,tank.c.y+tank.h);grad.addColorStop(0,state.night?"#0a435a":"#16869a");grad.addColorStop(.5,state.night?"#062f46":"#0b6478");grad.addColorStop(1,state.night?"#041f35":"#08475b");ctx.fillStyle=grad;ctx.fillRect(tank.c.x-tank.w,tank.c.y-tank.h*2,tank.w*2,tank.h*4);
    for(let n=0;n<18;n++){const x=tank.c.x+Math.sin(t*.00035+n*2.2+i)*tank.w*.46;const y=tank.c.y+Math.cos(t*.00028+n*1.7+i)*tank.h*.37;ctx.beginPath();ctx.ellipse(x,y,8+((n*7)%16),2.2,Math.sin(n)*.2,0,Math.PI*2);ctx.strokeStyle=state.night?"rgba(73,176,198,.18)":"rgba(153,239,232,.25)";ctx.lineWidth=1;ctx.stroke();}
    // Directional circulation streaks move only when at least one aerator is running.
    const running=t.fans.filter(Boolean).length;for(let n=0;n<Math.min(12,running*3);n++){const f=(t*.00011+n/12+i*.13)%1;const x=tank.c.x-tank.w*.36+f*tank.w*.72;const y=tank.c.y+Math.sin(f*8+t*.0008+i)*tank.h*.23;ctx.beginPath();ctx.ellipse(x,y,13,2,Math.sin(f*8)*.12,0,Math.PI*2);ctx.strokeStyle="rgba(118,238,222,.38)";ctx.lineWidth=1.2;ctx.stroke();}
    ctx.restore();ctx.strokeStyle="rgba(133,209,214,.38)";ctx.lineWidth=1.2;poly(inset,null,ctx.strokeStyle,1);
    // Four paddlewheel aerators mounted along the far long edge; each rotates independently.
    for(let k=0;k<4;k++){const f=(k-1.5)/4.4;const pos=tank.pt(f,.82);const on=t.fans[k]&&!state.feeding;drawRotor(pos.x,pos.y,Math.max(7,Math.min(12,width*.012)),on,t*.004*(on?1:0)+k*.2+i*.35);if(on){ctx.beginPath();ctx.arc(pos.x,pos.y+8,Math.max(10,width*.018),0,Math.PI*2);ctx.strokeStyle="rgba(103,233,209,.3)";ctx.lineWidth=1.3;ctx.stroke();}}
    // Tank label badge.
    ctx.restore();const label=tank.pt(-.34,-.35);ctx.fillStyle="rgba(3,20,29,.78)";ctx.beginPath();ctx.roundRect(label.x-31,label.y-11,62,22,6);ctx.fill();ctx.fillStyle="#e7fbff";ctx.font="700 10px system-ui";ctx.textAlign="center";ctx.fillText(t.name,label.x,label.y+4);
    if(state.selected===i){ctx.strokeStyle="#5ce5dc";ctx.lineWidth=2.5;poly(p,null,ctx.strokeStyle,2.5);}
  }
  function drawReservoir(t){const c={x:width*.67,y:height*.20},w=Math.min(width*.22,225)*state.zoom,h=Math.min(height*.10,82)*state.zoom;const p=[{x:c.x-w*.5,y:c.y-h*.25},{x:c.x+w*.5,y:c.y-h*.72},{x:c.x+w*.5,y:c.y+h*.30},{x:c.x-w*.5,y:c.y+h*.78}];poly(p,"#0b3547","#568b99",4);poly(p.map(v=>({x:c.x+(v.x-c.x)*.91,y:c.y+(v.y-c.y)*.82})),"#0b6b83","#3da8b6",1);ctx.save();ctx.beginPath();ctx.moveTo(p[0].x,p[0].y);p.slice(1).forEach(v=>ctx.lineTo(v.x,v.y));ctx.closePath();ctx.clip();for(let n=0;n<12;n++){const x=c.x+Math.sin(t*.0002+n)*w*.42,y=c.y+Math.cos(t*.00017+n*2)*h*.35;ctx.beginPath();ctx.ellipse(x,y,12,2,0,0,Math.PI*2);ctx.strokeStyle="rgba(142,226,226,.25)";ctx.stroke();}ctx.restore();ctx.fillStyle="#d7f5fb";ctx.font="700 11px system-ui";ctx.textAlign="center";ctx.fillText("RESERVOIR",c.x,c.y+4);}
  function drawFarm(t){ctx.clearRect(0,0,width,height);const sky=ctx.createLinearGradient(0,0,0,height);sky.addColorStop(0,state.night?"#071725":"#174b5a");sky.addColorStop(1,state.night?"#0a2635":"#0d3943");ctx.fillStyle=sky;ctx.fillRect(0,0,width,height);
    // Atmospheric glow and distant farm ground.
    const glow=ctx.createRadialGradient(width*.48,height*.42,10,width*.48,height*.42,width*.72);glow.addColorStop(0,state.night?"rgba(25,98,125,.16)":"rgba(109,209,190,.18)");glow.addColorStop(1,"rgba(0,0,0,0)");ctx.fillStyle=glow;ctx.fillRect(0,0,width,height);
    ctx.save();ctx.translate(width*.5,height*.52);ctx.rotate(-.48+state.orbit);ctx.fillStyle=state.night?"#203a3d":"#55766a";ctx.fillRect(-width*.42,-height*.46,width*.84,height*.92);ctx.strokeStyle="rgba(205,222,190,.15)";ctx.lineWidth=2;ctx.strokeRect(-width*.42,-height*.46,width*.84,height*.92);ctx.restore();
    drawReservoir(t);for(let i=3;i>=0;i--)drawWater(i,t);
    // Water inlet from reservoir to upper tank is a visual guide, not surveyed plumbing.
    ctx.beginPath();ctx.moveTo(width*.66,height*.27);ctx.quadraticCurveTo(width*.60,height*.30,width*.55,height*.36);ctx.strokeStyle="rgba(83,219,207,.45)";ctx.setLineDash([5,7]);ctx.lineWidth=2;ctx.stroke();ctx.setLineDash([]);
    // Day/night sun or moon.
    ctx.beginPath();ctx.arc(width*.12,height*.15, state.night?14:20,0,Math.PI*2);ctx.fillStyle=state.night?"#d7e8f4":"#ffd98a";ctx.shadowColor=ctx.fillStyle;ctx.shadowBlur=state.night?18:28;ctx.fill();ctx.shadowBlur=0;
    if(state.feeding){ctx.fillStyle="rgba(3,17,24,.78)";ctx.beginPath();ctx.roundRect(width*.5-82,24,164,27,8);ctx.fill();ctx.fillStyle="#f7d58a";ctx.font="700 10px system-ui";ctx.textAlign="center";ctx.fillText("FEEDING DEMO · AERATORS PAUSED",width*.5,42);}
    if(state.paused){ctx.fillStyle="rgba(3,17,24,.7)";ctx.fillRect(0,0,width,height);ctx.fillStyle="#fff";ctx.font="700 16px system-ui";ctx.textAlign="center";ctx.fillText("SIMULATION PAUSED",width/2,height/2);}
  }
  function metrics(){const t=tanks[state.selected];$("farmTwinSelectedName").textContent=t.name;$("farmTwinSelectedStatus").textContent="NORMAL · SIMULATED";$("farmTwinMetrics").innerHTML=[["Dissolved oxygen",t.do.toFixed(2),"mg/L"],["Temperature",t.temp.toFixed(1),"°C"],["pH",t.ph.toFixed(2),"pH"],["Salinity",t.sal.toFixed(1),"ppt"]].map(([a,b,c])=>'<div class="live-farm-metric"><span>'+a+'</span><strong>'+b+'</strong><small>'+c+' · simulated</small></div>').join("");$("farmTwinEquipment").innerHTML=t.fans.map((on,k)=>'<button type="button" class="'+(on&&!state.feeding?'is-on':'')+'" data-fan="'+k+'">Aerator '+(k+1)+' · '+(on&&!state.feeding?'RUNNING':'STOPPED')+'</button>').join("");$("farmTwinEquipment").querySelectorAll("[data-fan]").forEach(btn=>btn.addEventListener("click",()=>{t.fans[Number(btn.dataset.fan)]=!t.fans[Number(btn.dataset.fan)];metrics();}));$("farmTwinAssetList").innerHTML='<button class="live-farm-asset-button" data-asset="reservoir">Reservoir <small>Water source</small></button>'+tanks.map((v,i)=>'<button class="live-farm-asset-button '+(i===state.selected?'active':'')+'" data-asset="'+i+'">'+v.name+' <small>'+v.fans.filter(Boolean).length+'/4 aerators</small></button>').join("");$("farmTwinAssetList").querySelectorAll("[data-asset]").forEach(btn=>btn.addEventListener("click",()=>{if(btn.dataset.asset==="reservoir")return;state.selected=Number(btn.dataset.asset);metrics();}));}
  function tick(ts){if(!state.last)state.last=ts;const dt=Math.min(50,ts-state.last);state.last=ts;simTime+=dt;if(!state.paused){tanks.forEach((t,i)=>{const s=simTime/1000;t.do=clamp(5.65+i*.09+Math.sin(s*.035+i)*.12,4.8,7.2);t.temp=clamp(28.8+i*.12+Math.sin(s*.012+i*.5)*.18,27,32);t.ph=clamp(7.95+i*.02+Math.sin(s*.009+i)*.015,7.4,8.5);t.sal=clamp(18+i*.4+Math.sin(s*.004+i)*.08,10,35);});}
    const now=new Date();$("farmTwinClock").textContent=now.toLocaleTimeString();$("farmTwinEnvironment").textContent=(state.night?"Night scene":"Daylight scene")+" · visual simulation";if(state.feeding&&Date.now()>state.feedUntil){state.feeding=false;metrics();$("farmTwinFeed").textContent="▶ Start feeding demo";}drawFarm(ts);state.raf=requestAnimationFrame(tick);}
  function selectAt(x,y){for(let i=0;i<4;i++){const p=tankShape(i).corners;const minX=Math.min(...p.map(v=>v.x)),maxX=Math.max(...p.map(v=>v.x)),minY=Math.min(...p.map(v=>v.y)),maxY=Math.max(...p.map(v=>v.y));if(x>=minX&&x<=maxX&&y>=minY&&y<=maxY){state.selected=i;metrics();return;}}}
  canvas.addEventListener("pointerdown",e=>{state.drag={x:e.clientX,y:e.clientY,moved:false};canvas.setPointerCapture(e.pointerId);});canvas.addEventListener("pointermove",e=>{if(!state.drag)return;const dx=e.clientX-state.drag.x;if(Math.abs(dx)>2)state.drag.moved=true;state.orbit=clamp(state.orbit+dx*.0015,-.28,.28);state.drag.x=e.clientX;});canvas.addEventListener("pointerup",e=>{if(state.drag&&!state.drag.moved){const r=canvas.getBoundingClientRect();selectAt(e.clientX-r.left,e.clientY-r.top);}state.drag=null;});canvas.addEventListener("wheel",e=>{e.preventDefault();state.zoom=clamp(state.zoom+(e.deltaY<0?.04:-.04),.82,1.22);},{passive:false});
  $("farmTwinDayNight").addEventListener("click",()=>{state.night=!state.night;});
  $("farmTwinFeed").addEventListener("click",()=>{state.feeding=!state.feeding;state.feedUntil=Date.now()+30000;$("farmTwinFeed").textContent=state.feeding?"■ Stop feeding demo":"▶ Start feeding demo";metrics();});
  $("farmTwinReset").addEventListener("click",()=>{tanks.forEach(t=>t.fans=[true,true,true,true]);state.feeding=false;state.paused=false;state.zoom=1;state.orbit=0;$("farmTwinFeed").textContent="▶ Start feeding demo";metrics();});
  document.addEventListener("visibilitychange",()=>{if(document.hidden){cancelAnimationFrame(state.raf);}else{state.last=0;state.raf=requestAnimationFrame(tick);}});
  window.addEventListener("resize",resize);resize();metrics();state.raf=requestAnimationFrame(tick);
})();
