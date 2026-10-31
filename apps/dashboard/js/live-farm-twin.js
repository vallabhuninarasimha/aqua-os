/* Aqua OS — interactive 3D farm digital twin.
 * Three.js scene. All values and actuator states in this module are SIMULATION only.
 * No hardware commands are sent from this visualisation.
 */
(async () => {
  "use strict";
  const canvas = document.getElementById("aquaFarmTwinCanvas");
  if (!canvas || canvas.dataset.twin3dReady === "1") return;
  canvas.dataset.twin3dReady = "1";
  const $ = id => document.getElementById(id);
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  const tanks = [
    {id:1,name:"Tank 01",do:5.82,temp:28.4,ph:7.85,sal:24.2,nh3:.08,level:1.25,fans:[true,true,true,true]},
    {id:2,name:"Tank 02",do:5.64,temp:28.7,ph:7.90,sal:24.5,nh3:.12,level:1.22,fans:[true,true,true,false]},
    {id:3,name:"Tank 03",do:5.91,temp:28.2,ph:7.80,sal:23.8,nh3:.05,level:1.28,fans:[true,true,true,true]},
    {id:4,name:"Tank 04",do:4.88,temp:29.1,ph:7.95,sal:25.1,nh3:.19,level:1.20,fans:[true,true,true,true]}
  ];
  const state={selected:0,night:(new Date().getHours()<6||new Date().getHours()>=18),feeding:false,feedUntil:0,zoom:1,paused:false};
  let THREE, renderer, scene, camera, controlsTarget, raf=0, last=0, elapsed=0, observer;
  const tankObjects=[], aerators=[], waterMats=[];
  let raycaster, pointer;
  try {
    THREE = await import("https://cdn.jsdelivr.net/npm/three@0.161.0/build/three.module.js");
  } catch (err) {
    canvas.dataset.twin3dReady="0";
    const note=document.createElement("div"); note.className="live-farm-load-error";
    note.textContent="3D engine could not load. Check internet access and reload this view.";
    canvas.parentElement.appendChild(note);
    console.error("Aqua OS 3D engine load failed",err); return;
  }
  const width=()=>Math.max(1,canvas.clientWidth), height=()=>Math.max(1,canvas.clientHeight);
  renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:false,powerPreference:"high-performance"});
  renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));
  renderer.setSize(width(),height(),false);
  renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.toneMapping=THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=1.05;
  scene=new THREE.Scene(); scene.background=new THREE.Color(state.night?0x071522:0x9ab8c4);
  scene.fog=new THREE.Fog(state.night?0x071522:0x9ab8c4,48,105);
  camera=new THREE.PerspectiveCamera(42,width()/height(),.1,250);
  camera.position.set(0,38,64); controlsTarget=new THREE.Vector3(0,0,0);
  const hemi=new THREE.HemisphereLight(0xc8eaff,0x263b2c,state.night?.75:1.35); scene.add(hemi);
  const sun=new THREE.DirectionalLight(state.night?0x9dbbe8:0xffe2b4,state.night?1.1:2.2);
  sun.position.set(-18,32,14); sun.castShadow=true; sun.shadow.mapSize.set(2048,2048);
  sun.shadow.camera.left=-45;sun.shadow.camera.right=45;sun.shadow.camera.top=45;sun.shadow.camera.bottom=-45;scene.add(sun);
  const mat=(color,roughness=.8,metalness=0)=>new THREE.MeshStandardMaterial({color,roughness,metalness});
  const ground=new THREE.Mesh(new THREE.PlaneGeometry(100,70),mat(state.night?0x15231f:0x52644b));ground.rotation.x=-Math.PI/2;ground.position.y=-.45;ground.receiveShadow=true;scene.add(ground);
  const grid=new THREE.GridHelper(90,45,state.night?0x29404b:0x82917d,state.night?0x1c3039:0x71816e);grid.position.y=-.43;scene.add(grid);
  // Perimeter berms and service roads give the site a readable physical scale.
  function box(w,h,d,material,x,y,z){const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),material);m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;scene.add(m);return m;}
  const concrete=mat(0x879397), darkConcrete=mat(0x52636a), steel=mat(0x344d59,.42,.72);
  box(58,.35,1.2,concrete,0,-.15,-17);box(58,.35,1.2,concrete,0,-.15,17);
  box(1.2,.35,34,concrete,-29,-.15,0);box(1.2,.35,34,concrete,29,-.15,0);
  // Reservoir with raised concrete walls, visible water and a transfer channel.
  const reservoirGroup=new THREE.Group();reservoirGroup.position.set(0,0,-12);scene.add(reservoirGroup);
  const resWater=new THREE.Mesh(new THREE.PlaneGeometry(10,5.5,32,20),waterMaterial());resWater.rotation.x=-Math.PI/2;resWater.position.y=.08;reservoirGroup.add(resWater);
  addBasinWalls(reservoirGroup,10.8,6.3,1.05);
  const resLabel=labelSprite("RESERVOIR BASIN");resLabel.position.set(0,1.8,0);reservoirGroup.add(resLabel);
  // Transfer channel from reservoir to tank manifold.
  const pipe=new THREE.Mesh(new THREE.CylinderGeometry(.24,.24,14,16),mat(0x3d8290,.35,.45));pipe.rotation.x=Math.PI/2;pipe.position.set(0,.65,-3.1);scene.add(pipe);
  const pipePulse=new THREE.Mesh(new THREE.CylinderGeometry(.09,.09,13.6,12),mat(0x5bd4e5,.25,.3));pipePulse.rotation.x=Math.PI/2;pipePulse.position.set(0,.65,-3.1);scene.add(pipePulse);
  function waterMaterial(){
    return new THREE.ShaderMaterial({transparent:false,uniforms:{uTime:{value:0},uNight:{value:state.night?1:0},uEnergy:{value:.65}},vertexShader:`
      varying vec2 vUv; varying vec3 vWorld;
      uniform float uTime; uniform float uEnergy;
      void main(){vUv=uv; vec3 p=position; float flow=sin(p.y*2.8-uTime*2.0)*.075+sin(p.y*5.4-uTime*3.1+p.x*.35)*.025; float cross=sin(p.x*1.15+uTime*.8)*.018; float wake=sin(p.y*8.0-uTime*5.2)*.012; p.z+=(flow+cross+wake)*uEnergy; vec4 world=modelMatrix*vec4(p,1.0);vWorld=world.xyz;gl_Position=projectionMatrix*viewMatrix*world;}
    `,fragmentShader:`
      varying vec2 vUv; varying vec3 vWorld; uniform float uTime; uniform float uNight; uniform float uEnergy;
      void main(){float wave=sin(vUv.x*42.0+uTime*1.7)*cos(vUv.y*34.0-uTime*2.2);float ripple=sin(vUv.y*92.0-uTime*6.0+vUv.x*7.0);float glint=smoothstep(.48,.95,wave*.72+ripple*.28)*(.08+uEnergy*.20);vec3 day=mix(vec3(.015,.18,.24),vec3(.035,.39,.48),vUv.y);vec3 night=mix(vec3(.004,.035,.07),vec3(.012,.12,.19),vUv.y);vec3 col=mix(day,night,uNight);col+=glint*(.35+uEnergy*.65);gl_FragColor=vec4(col,1.0);}
    `,side:THREE.DoubleSide});
  }
  function addBasinWalls(group,w,d,h){
    const wallMat=concrete;
    const wall1=new THREE.Mesh(new THREE.BoxGeometry(w,h,.42),wallMat);wall1.position.set(0,h/2, -d/2);group.add(wall1);
    const wall2=wall1.clone();wall2.position.z=d/2;group.add(wall2);
    const wall3=new THREE.Mesh(new THREE.BoxGeometry(.42,h,d),wallMat);wall3.position.set(-w/2,h/2,0);group.add(wall3);
    const wall4=wall3.clone();wall4.position.x=w/2;group.add(wall4);
    const base=new THREE.Mesh(new THREE.BoxGeometry(w,h*.22,d),darkConcrete);base.position.y=-h*.11;group.add(base);
  }
  function labelSprite(text){
    const c=document.createElement("canvas");c.width=512;c.height=96;const x=c.getContext("2d");
    x.fillStyle="rgba(4,17,28,.86)";x.beginPath();x.roundRect(4,4,504,88,18);x.fill();
    x.strokeStyle="rgba(91,205,222,.8)";x.lineWidth=3;x.stroke();
    x.fillStyle="#effaff";x.font="bold 38px Arial";x.textAlign="center";x.textBaseline="middle";x.fillText(text,256,49);
    const tex=new THREE.CanvasTexture(c);tex.colorSpace=THREE.SRGBColorSpace;
    const s=new THREE.Sprite(new THREE.SpriteMaterial({map:tex,transparent:true,depthTest:false}));s.scale.set(5.6,1.05,1);return s;
  }
  function makeAerator(group,index){
    // Four independent, floating paddlewheel units per tank. The wheel axis and
    // blade pitch are consistent so all units drive circulation in one direction.
    const spots=[[-4.15,-2.05],[4.15,-2.05],[-4.15,2.05],[4.15,2.05]];
    const [px,pz]=spots[index];
    const g=new THREE.Group();g.position.set(px,0,pz);group.add(g);
    const floatMat=mat(0x0878c7,.32,.08), steelMat=mat(0x607985,.38,.72);
    // Twin sealed floats, cross braces and raised motor housing.
    for(const side of [-1,1]){
      const float=new THREE.Mesh(new THREE.CapsuleGeometry(.34,1.55,5,12),floatMat);
      float.rotation.z=Math.PI/2;float.position.set(side*.82,.12,0);float.scale.set(1,1,.82);
      float.castShadow=true;float.receiveShadow=true;g.add(float);
    }
    const frame=new THREE.Mesh(new THREE.BoxGeometry(2.5,.12,.18),steelMat);frame.position.y=.68;g.add(frame);
    const motor=new THREE.Mesh(new THREE.CylinderGeometry(.32,.38,.78,20),mat(0x145a91,.42,.25));
    motor.position.set(0,1.02,-.55);motor.castShadow=true;g.add(motor);
    const motorCap=new THREE.Mesh(new THREE.CylinderGeometry(.34,.34,.1,20),mat(0x9fb6c0,.35,.55));
    motorCap.position.set(0,1.43,-.55);g.add(motorCap);
    const shaft=new THREE.Mesh(new THREE.CylinderGeometry(.095,.095,2.15,16),steelMat);
    shaft.rotation.z=Math.PI/2;shaft.position.set(0,.94,0);g.add(shaft);
    const rotor=new THREE.Group();rotor.position.set(0,.94,0);g.add(rotor);
    const hub=new THREE.Mesh(new THREE.CylinderGeometry(.22,.22,.34,20),mat(0xd5e2e6,.3,.6));
    hub.rotation.z=Math.PI/2;rotor.add(hub);
    const bladeMat=mat(0xe5bd38,.48,.18);
    for(let n=0;n<10;n++){
      const blade=new THREE.Mesh(new THREE.BoxGeometry(.13,1.08,.56),bladeMat);
      blade.position.y=.68;blade.rotation.x=.10;blade.rotation.z=n*Math.PI/5;
      blade.castShadow=true;rotor.add(blade);
    }
    // Guard rails and a submerged paddle arc make the water contact readable.
    for(const side of [-1,1]){
      const post=new THREE.Mesh(new THREE.CylinderGeometry(.045,.045,.78,10),steelMat);
      post.position.set(side*1.08,.91,0);g.add(post);
    }
    const splash=new THREE.Mesh(new THREE.TorusGeometry(1.05,.035,8,56),new THREE.MeshBasicMaterial({color:0xb9f3ff,transparent:true,opacity:.0}));
    splash.position.set(0,.89,.05);splash.rotation.x=Math.PI/2;g.add(splash);
    const droplets=[];
    for(let n=0;n<14;n++){
      const drop=new THREE.Mesh(new THREE.SphereGeometry(.035+(n%3)*.012,8,6),new THREE.MeshBasicMaterial({color:0xd7f8ff,transparent:true,opacity:0}));
      g.add(drop);droplets.push(drop);
    }
    const light=new THREE.PointLight(0x38c8ed,.25,2.8);light.position.set(0,1.7,0);g.add(light);
    return {rotor,splash,light,group:g,droplets,index};
  }
  const tankPositions=[[-22,0],[-7.3,0],[7.3,0],[22,0]];
  tanks.forEach((t,i)=>{
    const group=new THREE.Group();group.position.set(tankPositions[i][0],0,tankPositions[i][1]);scene.add(group);
    const w=13.2,d=7.2,h=1.35;
    const base=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),darkConcrete);base.position.y=h/2-.15;base.castShadow=true;base.receiveShadow=true;group.add(base);
    const water=new THREE.Mesh(new THREE.PlaneGeometry(w-1,d-1,48,32),waterMaterial());water.rotation.x=-Math.PI/2;water.position.y=.88;water.receiveShadow=true;group.add(water);
    // thick rim and inner liner
    const rim=new THREE.Mesh(new THREE.BoxGeometry(w+.3,.22,d+.3),concrete);rim.position.y=1.18;group.add(rim);
    const inner=new THREE.Mesh(new THREE.BoxGeometry(w-.75,.08,d-.75),mat(0x123e4a,.35));inner.position.y=.99;group.add(inner);
    const cornerMat=mat(0x9ba8a8,.65);
    for(const [x,z,sx,sz] of [[0,-d/2,w,.35],[0,d/2,w,.35],[-w/2,0,.35,d],[w/2,0,.35,d]]){
      const edge=new THREE.Mesh(new THREE.BoxGeometry(sx,.35,sz),cornerMat);edge.position.set(x,1.25,z);edge.castShadow=true;group.add(edge);
    }
    // Tank-side service walkway and ladders.
    const walkway=new THREE.Mesh(new THREE.BoxGeometry(w+.9,.18,1.15),mat(0x65767a,.7,.25));walkway.position.set(0,.12,d/2+1.0);group.add(walkway);
    for(let k=0;k<4;k++){const rail=new THREE.Mesh(new THREE.CylinderGeometry(.045,.045,1.0,8),steel);rail.position.set(-5.7+k*3.8,.7,d/2+1.45);group.add(rail);}
    const label=labelSprite(t.name.toUpperCase());label.position.set(0,2.25,-d/2-.1);group.add(label);
    const devices=Array.from({length:4},(_,k)=>makeAerator(group,k));
    const selection=new THREE.Mesh(new THREE.BoxGeometry(w+.8,.08,d+.8),new THREE.MeshBasicMaterial({color:0x35c7e8,wireframe:true,transparent:true,opacity:.0}));selection.position.y=1.3;group.add(selection);
    group.userData={tankIndex:i,water,selection};
    tankObjects.push(group);aerators.push(devices);waterMats.push(water.material);
  });
  // Canal flow markers animated along the transfer pipe.
  const flowDots=[];
  for(let i=0;i<12;i++){const dot=new THREE.Mesh(new THREE.SphereGeometry(.09,10,8),new THREE.MeshBasicMaterial({color:0x9ceeff}));dot.position.set(0,.88,-9+i*.95);scene.add(dot);flowDots.push(dot);}
  raycaster=new THREE.Raycaster();pointer=new THREE.Vector2();
  function focusTank(index){state.selected=index;tankObjects.forEach((g,i)=>g.userData.selection.material.opacity=i===index?.75:0);const p=tankObjects[index].position;controlsTarget.set(p.x,0.7,p.z);theta=.62;phi=.82;radius=19;camera.position.set(p.x+10,10,p.z+15);camera.lookAt(controlsTarget);metrics();}
  function metrics(){
    const t=tanks[state.selected],name=$("farmTwinSelectedName"),status=$("farmTwinSelectedStatus"),box=$("farmTwinMetrics"),eq=$("farmTwinEquipment"),assets=$("farmTwinAssetList");
    if(name)name.textContent=t.name;
    if(status){status.textContent=t.do<5?"ATTENTION · LOW DO (SIMULATION)":"SIMULATION · DRY-RUN ONLY";status.className="live-farm-status "+(t.do<5?"status-warning":"status-normal");}
    if(box)box.innerHTML=[["Dissolved Oxygen",t.do.toFixed(2),"mg/L",t.do<5?"warning":"good"],["Water Temperature",t.temp.toFixed(1),"°C","good"],["Acidity / pH",t.ph.toFixed(2),"pH","good"],["Salinity",t.sal.toFixed(1),"ppt","good"],["Ammonia (NH₃)",t.nh3.toFixed(2),"mg/L",t.nh3>=.15?"warning":"good"],["Water Depth",t.level.toFixed(2),"m","good"]].map(([l,v,u,s])=>`<div class="live-farm-metric"><span>${l}</span><strong class="${s==="warning"?"text-amber":""}">${v} <small>${u}</small></strong><small class="metric-note">Simulation value</small></div>`).join("");
    if(eq){eq.innerHTML=t.fans.map((on,k)=>`<button type="button" class="live-farm-action ${on&&!state.feeding?"live-farm-action-primary":""}" data-fan="${k}">Aerator 0${k+1}: ${on&&!state.feeding?"RUNNING":"STOPPED"} · SIMULATION</button>`).join("");eq.querySelectorAll("[data-fan]").forEach(b=>b.addEventListener("click",()=>{t.fans[+b.dataset.fan]=!t.fans[+b.dataset.fan];metrics();}));}
    if(assets){assets.innerHTML=`<button class="live-farm-asset-button" data-asset="reservoir"><div><b>Reservoir Basin</b><small>Source · SIMULATION</small></div><span class="badge-blue">SOURCE</span></button>`+tanks.map((v,i)=>`<button class="live-farm-asset-button ${i===state.selected?"active":""}" data-asset="${i}"><div><b>${v.name}</b><small>DO: ${v.do.toFixed(1)} mg/L · SIMULATION</small></div><span class="badge-status">${v.fans.filter(Boolean).length}/4 Aerators</span></button>`).join("");assets.querySelectorAll("[data-asset]").forEach(b=>b.addEventListener("click",()=>{if(b.dataset.asset!=="reservoir")focusTank(+b.dataset.asset);}));}
  }
  function updateEnvironment(){
    const night=state.night;scene.background.set(night?0x071522:0x9ab8c4);scene.fog.color.set(night?0x071522:0x9ab8c4);
    hemi.intensity=night?.75:1.35;sun.intensity=night?1.1:2.2;sun.color.set(night?0x9dbbe8:0xffe2b4);
    waterMats.forEach(m=>m.uniforms.uNight.value=night?1:0);resWater.material.uniforms.uNight.value=night?1:0;
  }
  function resize(){const w=width(),h=height();renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
  observer=window.ResizeObserver?new ResizeObserver(resize):null;if(observer)observer.observe(canvas);
  window.addEventListener("resize",resize);
  // Pointer orbit, pan-free selection and wheel zoom. Dragging rotates around the farm centre.
  let drag=null,theta=Math.atan2(camera.position.x,camera.position.z),phi=Math.acos(camera.position.y/camera.position.length()),radius=camera.position.length();
  canvas.addEventListener("pointerdown",e=>{drag={x:e.clientX,y:e.clientY,moved:false};canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener("pointermove",e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;theta-=dx*.006;phi=clamp(phi+dy*.004,.25,1.35);drag.x=e.clientX;drag.y=e.clientY;});
  canvas.addEventListener("pointerup",e=>{if(drag&&!drag.moved){const r=canvas.getBoundingClientRect();pointer.set(((e.clientX-r.left)/r.width)*2-1,-((e.clientY-r.top)/r.height)*2+1);raycaster.setFromCamera(pointer,camera);const hits=raycaster.intersectObjects(tankObjects,true);const hit=hits.find(h=>{let p=h.object;while(p&&p!==scene){if(p.userData.tankIndex!==undefined)return true;p=p.parent;}return false;});if(hit){let p=hit.object;while(p&&p.userData.tankIndex===undefined)p=p.parent;if(p)focusTank(p.userData.tankIndex);}}drag=null;});
  canvas.addEventListener("wheel",e=>{e.preventDefault();radius=clamp(radius+(e.deltaY>0?2:-2),15,75);},{passive:false});
  const day=$("farmTwinDayNight");if(day)day.addEventListener("click",()=>{state.night=!state.night;updateEnvironment();});
  const feed=$("farmTwinFeed");if(feed)feed.addEventListener("click",()=>{state.feeding=!state.feeding;state.feedUntil=Date.now()+25000;feed.textContent=state.feeding?"■ Stop feeding demo":"▶ Start feeding demo";metrics();});
  const reset=$("farmTwinReset");if(reset)reset.addEventListener("click",()=>{tanks.forEach(t=>t.fans=[true,true,true,true]);state.feeding=false;state.zoom=1;theta=.65;phi=.7;theta=.0;phi=.95;radius=66;focusTank(0);if(feed)feed.textContent="▶ Start feeding demo";metrics();});
  function animate(ts){raf=requestAnimationFrame(animate);if(!last)last=ts;const dt=Math.min((ts-last)/1000,.05);last=ts;if(!state.paused)elapsed+=dt;
    if(state.feeding&&Date.now()>state.feedUntil){state.feeding=false;if(feed)feed.textContent="▶ Start feeding demo";metrics();}
    tanks.forEach((t,i)=>{const s=elapsed;t.do=clamp(5.65+i*.08+Math.sin(s*.04+i)*.15,4.4,7.2);t.temp=clamp(28.4+i*.15+Math.sin(s*.02+i*.5)*.2,27,31.5);t.ph=clamp(7.85+i*.02+Math.sin(s*.01+i)*.02,7.5,8.4);t.sal=clamp(24+i*.3+Math.sin(s*.005+i)*.1,15,35);
      aerators[i].forEach((a,k)=>{const on=t.fans[k]&&!state.feeding;a.rotor.rotation.x=on?elapsed*7.5:0;a.splash.material.opacity=on?.28+.16*Math.sin(elapsed*4+k):.015;a.splash.scale.setScalar(on?1+.12*Math.sin(elapsed*5+k):.72);a.light.intensity=on?1.1:.04;a.droplets.forEach((d,n)=>{const phase=(elapsed*1.7+n*.19+k*.31)%1;d.visible=on;d.position.set(Math.sin(n*2.4+k)*(.28+phase*.9),on?.92+Math.sin(phase*Math.PI)*(.22+(n%4)*.11):.9,Math.cos(n*2.4+k)*(.22+phase*.65));d.material.opacity=on?Math.sin(phase*Math.PI)*.82:0;});});
      waterMats[i].uniforms.uTime.value=elapsed;waterMats[i].uniforms.uEnergy.value=t.fans.filter(Boolean).length/4*(state.feeding?.12:1);
    });
    resWater.material.uniforms.uTime.value=elapsed;flowDots.forEach((d,i)=>{d.position.z=-9+((elapsed*1.6+i*1.15)%13.6);d.position.y=.85+Math.sin(elapsed*2+i)*.08;});
    const clock=$("farmTwinClock");if(clock)clock.textContent=new Date().toLocaleTimeString();const env=$("farmTwinEnvironment");if(env)env.textContent=(state.night?"Night":"Daylight")+" · 3D Digital Twin · SIMULATION";
    const target=tankObjects[state.selected].position;const r=radius;camera.position.set(controlsTarget.x+Math.sin(theta)*Math.sin(phi)*r,Math.cos(phi)*r,controlsTarget.z+Math.cos(theta)*Math.sin(phi)*r);camera.lookAt(controlsTarget);renderer.render(scene,camera);
  }
  updateEnvironment();tankObjects.forEach((g,i)=>g.userData.selection.material.opacity=i===0?.75:0);metrics();resize();
  window.initLiveFarmTwin=()=>{resize();metrics();};
  document.addEventListener("visibilitychange",()=>{if(document.hidden)cancelAnimationFrame(raf);else{last=0;raf=requestAnimationFrame(animate);}});
  raf=requestAnimationFrame(animate);
})();
