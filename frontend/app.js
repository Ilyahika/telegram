/* QWE: navigation, Telegram authentication and purely arcade mini-games.
 * No money stakes. Profile and bonuses always come from the server. */
const tg = window.Telegram?.WebApp;
const $ = id => document.getElementById(id);
let profile = null, currentGame = null, gameTimer = null;
const toast = (message) => { $('toast').textContent=message; $('toast').classList.add('show'); setTimeout(()=>$('toast').classList.remove('show'),2600); };
function navigate(name) {
  document.querySelectorAll('.screen').forEach(x=>x.classList.toggle('active',x.id===`screen-${name}`));
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.page===name));
  window.scrollTo({top:0,behavior:'smooth'});
}
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.page)));
function paint(p) {
  profile=p;
  const values={'player-name':p.display_name,'player-subtitle':`ID ${p.telegram_id}`,'level':p.level,'points':p.points,'bitcoin':Number(p.bitcoin).toFixed(6),'bank-points':p.bank_points,'bank-rate':`${p.bank_rate}%`,'bank-big':p.bank_points,'games-played':p.games_played,'win-loss':`${p.games_won} / ${p.games_lost}`,'win-rate':p.games_played?`${Math.round(100*p.games_won/p.games_played)}%`:'0%','favorite-game':p.favorite_game,'property':p.property_name};
  for (const [id,value] of Object.entries(values)) $(id).textContent=value??'—';
  $('avatar').textContent=(p.display_name||'Q').trim().slice(0,1).toUpperCase();
  // Only the server can authorize admin routes; this button is just a visual convenience.
  $('admin-button').classList.toggle('hidden',Number(p.telegram_id)!==1181838335);
}
async function request(path,data) {
 const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:tg?.initData||'',...data})});
 const body=await res.json().catch(()=>({}));
 if(!res.ok)throw new Error(typeof body.detail==='string'?body.detail:`Ошибка ${res.status}`);
 return body;
}
document.querySelectorAll('[data-bonus]').forEach(b=>b.addEventListener('click',async()=>{
 b.disabled=true;
 try {const result=await request('/api/bonus',{kind:b.dataset.bonus});profile.points=result.points;paint(profile);toast(`+${result.awarded} очков начислено`);} catch(e){toast(e.message);} finally{b.disabled=false;}
}));
$('admin-button').addEventListener('click',async()=>{
 try {const info=await request('/api/admin/status',{});$('admin-output').classList.remove('hidden');$('admin-output').textContent=`Зарегистрировано игроков: ${info.players_count}`;}catch(e){toast(e.message);}
});
function stopGame(){if(gameTimer){clearInterval(gameTimer);gameTimer=null;}}
function pickGame(name){stopGame();currentGame=name;const titles={crash:'Краш · реакция',wheel:'Апдейт · колесо',mines:'Мины · память',plinko:'Плинко · аркада'};$('game-title').textContent=titles[name];$('play-button').classList.remove('hidden');$('play-button').textContent='Начать';const messages={crash:'Нажми «Начать», затем останови растущую шкалу до её заполнения.',wheel:'Колесо вращается. Нажми «Стоп» как можно ближе к подсвеченному сектору.',mines:'Открой все безопасные клетки. Попадание на мину завершит раунд.',plinko:'Наблюдай за движением шарика по неоновым штырькам.'};$('playfield').textContent=messages[name];}
document.querySelectorAll('[data-game]').forEach(b=>b.addEventListener('click',()=>pickGame(b.dataset.game)));
$('play-button').addEventListener('click',()=>{
 const field=$('playfield'),btn=$('play-button');stopGame();
 if(currentGame==='crash'){
  if(btn.textContent==='Остановить')return;
  let progress=0;btn.textContent='Остановить';field.innerHTML='<div class="meter"><div id="meter-fill"></div></div><strong id="meter-value">1.00×</strong>';
  gameTimer=setInterval(()=>{progress+=1.4;$('meter-fill').style.width=`${progress}%`;$('meter-value').textContent=`${(1+progress/50).toFixed(2)}×`;if(progress>=100){stopGame();field.innerHTML='<b>Шкала заполнилась!</b><small>Попробуй остановить раньше.</small>';btn.textContent='Повторить';}},45);
  btn.onclick=()=>{if(!gameTimer)return;stopGame();field.innerHTML=`<b>Остановлено: ${(1+progress/50).toFixed(2)}×</b><small>Это показатель реакции, не денежный выигрыш.</small>`;btn.textContent='Повторить';btn.onclick=null;};
 } else if(currentGame==='wheel'){
  let angle=0;field.innerHTML='<div class="wheel"></div><small>Цель: остановить близко к отметке сверху.</small>';btn.textContent='Стоп';
  gameTimer=setInterval(()=>{angle+=11;field.querySelector('.wheel').style.transform=`rotate(${angle}deg)`;},40);
  btn.onclick=()=>{stopGame();const deviation=Math.min(angle%90,90-(angle%90));field.insertAdjacentHTML('beforeend',`<strong>Отклонение: ${deviation.toFixed(0)}°</strong>`);btn.textContent='Повторить';btn.onclick=null;};
 } else if(currentGame==='mines'){
  const mines=new Set();while(mines.size<4)mines.add(Math.floor(Math.random()*25));let opened=0;field.innerHTML='<div class="mine-grid"></div><small>На поле 25 клеток и 4 скрытые мины.</small>';const grid=field.querySelector('.mine-grid');for(let i=0;i<25;i++){const cell=document.createElement('button');cell.className='mine-cell';cell.textContent='✦';cell.onclick=()=>{if(cell.disabled)return;cell.disabled=true;if(mines.has(i)){cell.textContent='✕';cell.classList.add('mine-bad');grid.querySelectorAll('button').forEach(x=>x.disabled=true);toast('Мина! Раунд завершён.');}else{cell.textContent='✓';cell.classList.add('mine-good');opened++;if(opened===21)toast('Все безопасные клетки открыты!');}};grid.append(cell);}btn.textContent='Новое поле';
 } else if(currentGame==='plinko'){
  field.innerHTML='<div class="plinko-board"><div class="plinko-ball" id="ball"></div><div class="plinko-pegs">'+Array.from({length:7},(_,i)=>'<div>'+Array.from({length:i+3},()=>'<span>•</span>').join('')+'</div>').join('')+'</div></div><small>Шарик проходит через поле.</small>';btn.disabled=true;let x=0,y=0,t=0;gameTimer=setInterval(()=>{t++;y=Math.min(260,t*4.4);x+=Math.random()>.5?10:-10;x=Math.max(-90,Math.min(90,x));$('ball').style.transform=`translate(${x}px,${y}px)`;if(y>=260){stopGame();btn.disabled=false;btn.textContent='Ещё раз';toast('Финиш!');}},40);
 }
});
async function initialize(){const begin=Date.now();if(tg){tg.ready();tg.expand();tg.setHeaderColor?.('#09091b');}if(tg?.initData){try{const data=await request('/api/auth',{});paint(data.player);}catch(e){$('player-subtitle').textContent='Ошибка входа';toast(e.message);}}else{$('player-subtitle').textContent='Демо: открой через Telegram';}await new Promise(r=>setTimeout(r,Math.max(0,1300-(Date.now()-begin))));$('app').classList.remove('is-hidden');$('splash').classList.add('is-gone');}
initialize();
