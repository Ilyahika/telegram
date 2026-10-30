'use strict';
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const worldCard = document.getElementById('worldCard');
const joystick = document.getElementById('joystick');
const knob = document.getElementById('joystickKnob');
let w=0,h=0,scale=1,toastTimer=null;
const player={x:.5,y:.57,dir:1};
const pet={x:.43,y:.63,phase:0};
const keys=new Set();
const input={x:0,y:0};
const island={cx:.51,cy:.5,rx:.39,ry:.37};
const trees=[[-.26,-.19,1],[-.16,-.31,.8],[.08,-.31,.95],[.28,-.19,.9],[-.30,.11,.78],[.27,.15,1],[-.16,.25,.8],[.13,.24,.82]];
const stones=[[-.25,.00],[-.04,-.25],[.22,.03],[.04,.25]];
function resize(){const r=canvas.getBoundingClientRect();w=r.width;h=r.height;const d=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.round(w*d);canvas.height=Math.round(h*d);ctx.setTransform(d,0,0,d,0,0);scale=Math.min(w/380,h/370)}
window.addEventListener('resize',resize);resize();
function ellipse(x,y,rx,ry,color){ctx.fillStyle=color;ctx.beginPath();ctx.ellipse(x,y,rx,ry,0,0,Math.PI*2);ctx.fill()}
function round(x,y,width,height,r,color){ctx.fillStyle=color;ctx.beginPath();ctx.roundRect(x,y,width,height,r);ctx.fill()}
function px(nx){return nx*w}function py(ny){return ny*h}
function tree(x,y,s){const r=11*s*scale;round(x-3*s*scale,y-3*s*scale,6*s*scale,18*s*scale,2,'#815f44');ellipse(x,y-9*s*scale,r,r*.8,'#174e3e');ellipse(x-5*s*scale,y-14*s*scale,r*.8,r*.82,'#278c56');ellipse(x+5*s*scale,y-18*s*scale,r*.7,r*.83,'#3aab66');ellipse(x-4*s*scale,y-19*s*scale,3*s*scale,2*s*scale,'#8be5a0')}
function drawBuilding(x,y){const s=scale;ellipse(x,y+16*s,43*s,13*s,'#4d9456');round(x-30*s,y-19*s,60*s,49*s,7*s,'#e2c99b');round(x-38*s,y-28*s,76*s,17*s,5*s,'#805a69');ctx.fillStyle='#ac7580';ctx.beginPath();ctx.moveTo(x-43*s,y-23*s);ctx.lineTo(x,y-54*s);ctx.lineTo(x+43*s,y-23*s);ctx.closePath();ctx.fill();round(x-8*s,y+3*s,16*s,27*s,3*s,'#7e6057');round(x-25*s,y-6*s,10*s,12*s,2*s,'#68c5d4');round(x+15*s,y-6*s,10*s,12*s,2*s,'#68c5d4');round(x-9*s,y-57*s,18*s,9*s,4*s,'#62d7d3')}
const petSprite=new Image();petSprite.src='/static/monsters/leafy-icon.svg';window.setCompanionSprite=(url)=>{if(url)petSprite.src=url};
function drawActor(x,y,isPet,t){const s=scale;ellipse(x,y+12*s,isPet?12*s:13*s,5*s,'#0000003c');if(isPet&&petSprite.complete&&petSprite.naturalWidth){ctx.drawImage(petSprite,x-18*s,y-31*s+Math.sin(t*3)*2*s,36*s,36*s);return;}if(isPet){const bob=Math.sin(t*3+1)*2*s;ellipse(x,y-5*s+bob,12*s,11*s,'#63c56e');ellipse(x-7*s,y-15*s+bob,6*s,8*s,'#79d980');ellipse(x+7*s,y-15*s+bob,6*s,8*s,'#58ad5c');ellipse(x-4*s,y-6*s+bob,1.8*s,2*s,'#13372e');ellipse(x+4*s,y-6*s+bob,1.8*s,2*s,'#13372e');ellipse(x,y-2*s+bob,2*s,1*s,'#d0f2bd');}else{const bob=Math.sin(t*8)*.8*s;round(x-7*s,y-1*s+bob,14*s,14*s,4*s,'#2c668f');round(x-8*s,y-19*s+bob,16*s,19*s,6*s,'#f5bc8c');ellipse(x,y-19*s+bob,9*s,8*s,'#4e3b64');ellipse(x+player.dir*3*s,y-12*s+bob,1.2*s,1.3*s,'#21354b');round(x-11*s,y+1*s+bob,5*s,9*s,3*s,'#5bb6d8');round(x+6*s,y+1*s+bob,5*s,9*s,3*s,'#5bb6d8')}}
function draw(t){ctx.clearRect(0,0,w,h);ctx.fillStyle='#58b5d4';ctx.fillRect(0,0,w,h);
for(let i=0;i<16;i++){const x=((i*97+24)%400)/400*w,y=((i*149+53)%420)/420*h;ctx.strokeStyle='#c5f9f84a';ctx.lineWidth=2;ctx.beginPath();ctx.arc(x+Math.sin(t+i)*5,y,4+(i%3)*3,0,Math.PI);ctx.stroke()}
const cx=px(island.cx),cy=py(island.cy),rx=w*island.rx,ry=h*island.ry;ellipse(cx,cy+10*scale,rx+9*scale,ry+13*scale,'#e6d4a0');ellipse(cx,cy,rx,ry,'#75bd72');ellipse(cx,cy-5*scale,rx*.97,ry*.94,'#8dd380');
ctx.strokeStyle='#d8bd89';ctx.lineWidth=15*scale;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(cx-10*scale,cy+ry*.76);ctx.quadraticCurveTo(cx-25*scale,cy+60*scale,cx-3*scale,cy+8*scale);ctx.quadraticCurveTo(cx+28*scale,cy-25*scale,cx+58*scale,cy-55*scale);ctx.stroke();
for(const [dx,dy] of stones){ellipse(cx+dx*w,cy+dy*h,6*scale,5*scale,'#b7bea5');ellipse(cx+dx*w-2*scale,cy+dy*h-2*scale,3*scale,2*scale,'#e5dfca')}
for(let i=0;i<32;i++){const a=i*2.4,r=.1+(i%6)*.043;const x=cx+Math.cos(a)*rx*r*2,y=cy+Math.sin(a)*ry*r*2;if(Math.abs(x-cx)<rx*.85&&Math.abs(y-cy)<ry*.82){ellipse(x,y,2*scale,2*scale,i%4===0?'#ffefb2':'#42a561')}}
for(const [dx,dy,s] of trees)tree(cx+dx*w,cy+dy*h,s);
drawBuilding(cx+34*scale,cy-76*scale);
const items=[{y:pet.y,render:()=>drawActor(px(pet.x),py(pet.y),true,t)},{y:player.y,render:()=>drawActor(px(player.x),py(player.y),false,t)}].sort((a,b)=>a.y-b.y);items.forEach(o=>o.render());
}
let last=performance.now();
function loop(now){const dt=Math.min((now-last)/1000,.04);last=now;let dx=0,dy=0;
if(keys.has('a')||keys.has('arrowleft'))dx--;if(keys.has('d')||keys.has('arrowright'))dx++;if(keys.has('w')||keys.has('arrowup'))dy--;if(keys.has('s')||keys.has('arrowdown'))dy++;dx+=input.x;dy+=input.y;const len=Math.hypot(dx,dy);if(len>.02){dx/=len;dy/=len;const nx=player.x+dx*dt*.17,ny=player.y+dy*dt*.17;const ex=(nx-island.cx)/island.rx,ey=(ny-island.cy)/island.ry;if(ex*ex+ey*ey<.84){player.x=nx;player.y=ny;}if(Math.abs(dx)>.08)player.dir=dx>0?1:-1}
const pd=Math.hypot(player.x-pet.x,player.y-pet.y);if(pd>.065){const f=Math.min(dt*2.2,(pd-.06)/pd);pet.x+=(player.x-pet.x)*f;pet.y+=(player.y-pet.y)*f}
draw(now/1000);document.getElementById('coords').textContent=`X: ${Math.round(player.x*100)} · Y: ${Math.round(player.y*100)}`;requestAnimationFrame(loop)}requestAnimationFrame(loop);
window.addEventListener('keydown',e=>{const k=e.key.toLowerCase();if(['arrowup','arrowdown','arrowleft','arrowright','w','a','s','d'].includes(k)){keys.add(k);e.preventDefault()}});window.addEventListener('keyup',e=>keys.delete(e.key.toLowerCase()));window.addEventListener('blur',()=>{keys.clear();input.x=input.y=0;knob.style.transform='translate(0,0)'});
let pointer=null;function joyMove(e){const r=joystick.getBoundingClientRect(),x=e.clientX-(r.left+r.width/2),y=e.clientY-(r.top+r.height/2),m=Math.max(1,Math.hypot(x,y)),dist=Math.min(m,21);input.x=x/m;input.y=y/m;knob.style.transform=`translate(${input.x*dist}px,${input.y*dist}px)`}joystick.addEventListener('pointerdown',e=>{pointer=e.pointerId;joystick.setPointerCapture(pointer);joyMove(e)});joystick.addEventListener('pointermove',e=>{if(e.pointerId===pointer)joyMove(e)});function joyEnd(e){if(e.pointerId!==pointer)return;pointer=null;input.x=input.y=0;knob.style.transform='translate(0,0)'}joystick.addEventListener('pointerup',joyEnd);joystick.addEventListener('pointercancel',joyEnd);
// Tap a point on the map to move toward it until reached.
let target=null;canvas.addEventListener('pointerdown',e=>{const r=canvas.getBoundingClientRect();const x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;const nx=(x-island.cx)/island.rx,ny=(y-island.cy)/island.ry;if(nx*nx+ny*ny<.84)target={x,y}});
function moveToTarget(){if(target&&keys.size===0&&pointer===null){const dx=target.x-player.x,dy=target.y-player.y,d=Math.hypot(dx,dy);if(d<.015){target=null;input.x=input.y=0}else{input.x=dx/d;input.y=dy/d}}else if(keys.size||pointer!==null){target=null}}
setInterval(moveToTarget,40);
const toast=document.getElementById('toast');function showToast(msg){toast.textContent=msg;toast.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.classList.remove('show'),2700)}document.querySelectorAll('[data-feature]').forEach(b=>b.addEventListener('click',()=>{let n=b.dataset.feature;showToast(n==='Остров'?'Ты уже на своём острове 🏝️':`${n} — появится в следующем обновлении ✨`)}));document.getElementById('interactButton').addEventListener('click',()=>showToast('Листик рад приключениям! 🌱'));
document.getElementById('soundButton').addEventListener('click',()=>showToast('Звуки добавим в следующем обновлении 🎵'));
(async()=>{try{const response=await fetch('/api/demo-profile');if(!response.ok)throw new Error('API error');const user=await response.json();const telegramUser=window.Telegram?.WebApp?.initDataUnsafe?.user;document.getElementById('playerName').textContent=telegramUser?.first_name||user.nickname;document.getElementById('coinBalance').textContent=user.coins.toLocaleString('ru-RU');document.getElementById('crystalBalance').textContent=user.crystals.toLocaleString('ru-RU');window.Telegram?.WebApp?.ready();window.Telegram?.WebApp?.expand();}catch(e){console.warn('Demo API unreachable',e)}})();
