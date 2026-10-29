/* QWE: navigation, Telegram authentication and purely arcade mini-games.
 * No money stakes. Profile and bonuses always come from the server. */
const tg = window.Telegram?.WebApp;
const $ = id => document.getElementById(id);
let profile = null, currentGame = null, gameTimer = null;
const toast = (message) => { $('toast').textContent=message; $('toast').classList.add('show'); setTimeout(()=>$('toast').classList.remove('show'),2600); };
function navigate(name) {
  // WebSocket остаётся подключённым при смене вкладки: общий раунд идёт всегда.
  document.querySelectorAll('.screen').forEach(x=>x.classList.toggle('active',x.id===`screen-${name}`));
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.page===name));
  window.scrollTo({top:0,behavior:'smooth'});
}
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.page)));
function paint(p) {
  profile=p; $('header-balance').textContent=`${Number(p.points).toLocaleString('ru-RU')} ₽`; $('bank-rate-detail').textContent=`${p.bank_rate}%`; 
  const values={'player-name':p.display_name,'player-subtitle':`ID ${p.telegram_id}`,'level':p.level,'points':`${Number(p.points).toLocaleString('ru-RU')} ₽`,'bitcoin':Number(p.bitcoin).toFixed(6),'bank-points':`${Number(p.bank_points).toLocaleString('ru-RU')} ₽`,'bank-rate':`${p.bank_rate}%`,'bank-big':`${Number(p.bank_points).toLocaleString('ru-RU')} ₽`,'games-played':p.games_played,'win-loss':`${p.games_won} / ${p.games_lost}`,'win-rate':p.games_played?`${Math.round(100*p.games_won/p.games_played)}%`:'0%','favorite-game':p.favorite_game,'property':p.property_name};
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
 try {const result=await request('/api/bonus',{kind:b.dataset.bonus});profile.points=result.points;paint(profile);toast(`+${result.awarded} игровых ₽ начислено`);} catch(e){toast(e.message);} finally{b.disabled=false;}
}));
$('admin-button').addEventListener('click',async()=>{
 try {const info=await request('/api/admin/status',{});$('admin-output').classList.remove('hidden');$('admin-output').textContent=`Зарегистрировано игроков: ${info.players_count}`;$('admin-controls').classList.remove('hidden');}catch(e){toast(e.message);}
});
function stopGame(){if(gameTimer){clearInterval(gameTimer);gameTimer=null;}}
function pickGame(name){stopGame();currentGame=name;
  $('live-crash').classList.toggle('hidden', name!=='crash');
  $('playroom').classList.toggle('hidden', name==='crash');const titles={crash:'Краш · общий LIVE',wheel:'Апдейт · колесо',mines:'Мины · память',plinko:'Плинко · аркада',memory:'Неоновая память',pulse:'Пульс · точность'};$('game-title').textContent=titles[name];$('play-button').classList.remove('hidden');$('play-button').textContent='Начать';const messages={crash:'Нажми «Начать», затем останови растущую шкалу до её заполнения.',wheel:'Колесо вращается. Нажми «Стоп» как можно ближе к подсвеченному сектору.',mines:'Открой все безопасные клетки. Попадание на мину завершит раунд.',plinko:'Наблюдай за движением шарика по неоновым штырькам.',memory:'Повтори световой рисунок на четырёх кнопках.',pulse:'Нажми стоп, когда маркер окажется в центре.'};$('playfield').textContent=messages[name];}
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
 } else if(currentGame==='memory'){
  // Показываем небольшую последовательность, затем проверяем ввод игрока.
  const sequence=Array.from({length:4},()=>Math.floor(Math.random()*4));let index=0;
  field.innerHTML='<div class="memory-grid"></div><small>Сначала запомни подсвеченные клетки…</small>';
  const grid=field.querySelector('.memory-grid');btn.disabled=true;
  const cells=Array.from({length:4},(_,i)=>{const cell=document.createElement('button');cell.className='memory-cell';cell.textContent=['✦','◆','✧','◈'][i];grid.append(cell);return cell;});
  (async()=>{for(const i of sequence){await new Promise(r=>setTimeout(r,570));cells[i].classList.add('lit');await new Promise(r=>setTimeout(r,360));cells[i].classList.remove('lit');}field.querySelector('small').textContent='Теперь повтори последовательность!';cells.forEach((cell,i)=>{cell.onclick=()=>{if(i!==sequence[index]){field.querySelector('small').textContent='Не совпало. Попробуй ещё раз!';cells.forEach(c=>c.disabled=true);return;}cell.classList.add('lit');setTimeout(()=>cell.classList.remove('lit'),240);index++;if(index===sequence.length){field.querySelector('small').textContent='Отличная память! Все четыре верно.';cells.forEach(c=>c.disabled=true);}};});btn.disabled=false;btn.textContent='Ещё раз';})();
 } else if(currentGame==='pulse'){
   let progress=0,direction=1;field.innerHTML='<div class="pulse-track"><div class="pulse-target"></div><div id="pulse-marker"></div></div><small>Останови маркер в светящейся зоне!</small>';
   btn.textContent='Стоп';gameTimer=setInterval(()=>{progress+=direction*1.8;if(progress>=100){progress=100;direction=-1;}if(progress<=0){progress=0;direction=1;}$('pulse-marker').style.left=`${progress}%`;},20);
   btn.onclick=()=>{stopGame();const delta=Math.abs(progress-50);field.querySelector('small').textContent=delta<8?'Идеально!':delta<18?'Очень близко!':'Попробуй точнее!';btn.textContent='Ещё раз';btn.onclick=null;};
 } else if(currentGame==='plinko'){
  field.innerHTML='<div class="plinko-board"><div class="plinko-ball" id="ball"></div><div class="plinko-pegs">'+Array.from({length:7},(_,i)=>'<div>'+Array.from({length:i+3},()=>'<span>•</span>').join('')+'</div>').join('')+'</div></div><small>Шарик проходит через поле.</small>';btn.disabled=true;let x=0,y=0,t=0;gameTimer=setInterval(()=>{t++;y=Math.min(260,t*4.4);x+=Math.random()>.5?10:-10;x=Math.max(-90,Math.min(90,x));$('ball').style.transform=`translate(${x}px,${y}px)`;if(y>=260){stopGame();btn.disabled=false;btn.textContent='Ещё раз';toast('Финиш!');}},40);
 }
});
async function initialize(){const begin=Date.now();if(tg){tg.ready();tg.expand();tg.setHeaderColor?.('#09091b');}if(tg?.initData){try{const data=await request('/api/auth',{});paint(data.player);}catch(e){$('player-subtitle').textContent='Ошибка входа';toast(e.message);}}else{$('player-subtitle').textContent='Демо: открой через Telegram';}await new Promise(r=>setTimeout(r,Math.max(0,1300-(Date.now()-begin))));$('app').classList.remove('is-hidden');$('splash').classList.add('is-gone');}
initialize();


/* LIVE CRASH — WebSocket получает единый таймер и результат от сервера.
 * Клиент ничего не рассчитывает и не отправляет результаты назад. */
let crashSocket = null;
let latestCrash = null;
let crashReconnect = null;
let lastCrashRound = 0;
let graphPoints = [];
function drawCrash(state) {
  const { phase, multiplier, round, ends_at, server_time, history } = state;
  $('crash-round').textContent = `Раунд #${round}`;
  $('crash-multiplier').innerHTML = `${Number(multiplier).toFixed(2)}<span>×</span>`;
  $('crash-stage').classList.toggle('crashed', phase === 'finished');
  $('crash-status').textContent = phase === 'running' ? '● ИДЁТ РАУНД' : phase === 'finished' ? '■ РАУНД ЗАВЕРШЁН' : '◷ ОЖИДАНИЕ';
  $('crash-hint').textContent = phase === 'running' ? 'Множитель растёт для всех игроков одновременно' : phase === 'finished' ? 'Раунд завершён. Следующий через 20 секунд.' : 'Подготовка к общему раунду';
  if (round !== lastCrashRound) { graphPoints = []; lastCrashRound = round; }
  if (phase === 'running' || phase === 'finished') {
    if (graphPoints.length === 0 || Math.abs(multiplier - graphPoints[graphPoints.length - 1]) > 0.01) graphPoints.push(multiplier);
  }
  // Сжимаем точки в пространство SVG, чтобы график помещался на телефоне.
  const n = Math.max(graphPoints.length, 2);
  const maximum = Math.max(2.2, ...graphPoints) * 1.12;
  const coords = graphPoints.map((v,i)=>[Math.round(i/(n-1)*342+9), Math.round(202-(v-1)/(maximum-1)*180)]);
  if (coords.length===1) coords.unshift([9,202]);
  const path = coords.length ? coords.map((pt,i)=>`${i?'L':'M'}${pt[0]} ${pt[1]}`).join(' ') : 'M9 202';
  $('crash-line').setAttribute('d',path);
  $('crash-area').setAttribute('d',coords.length ? `${path} L${coords[coords.length-1][0]} 202 L9 202 Z` : 'M9 202');
  const end = coords[coords.length-1] || [9,202];
  $('crash-head').setAttribute('cx',end[0]); $('crash-head').setAttribute('cy',end[1]);
  $('crash-history-items').replaceChildren(...(history.length ? history.slice().reverse().map(v=>{
    const chip=document.createElement('span'); chip.className='crash-chip '+(v>=2?'good':''); chip.textContent=`${Number(v).toFixed(2)}×`;return chip;
  }) : [Object.assign(document.createElement('span'),{textContent:'Нет завершённых раундов'})]));
  latestCrash = {phase, ends_at, server_time, receivedAt: Date.now()};
}
function tickCrashClock() {
  if(!latestCrash) return;
  const serverNow=latestCrash.server_time+(Date.now()-latestCrash.receivedAt)/1000;
  const seconds=Math.max(0, Math.ceil(latestCrash.ends_at-serverNow));
  $('crash-countdown').textContent=latestCrash.phase==='running'?'Идёт раунд':`${seconds} сек`;
}
setInterval(tickCrashClock,250);
function connectCrash() {
  if (crashSocket && (crashSocket.readyState===0 || crashSocket.readyState===1))return;
  const scheme=location.protocol==='https:'?'wss:':'ws:';
  crashSocket=new WebSocket(`${scheme}//${location.host}/ws/crash`);
  crashSocket.onopen=()=>{$('crash-connection').textContent='● LIVE';};
  crashSocket.onmessage=event=>{try{drawCrash(JSON.parse(event.data));}catch(e){console.error('Crash state:',e);}};
  crashSocket.onclose=()=>{
    $('crash-connection').textContent='○ ПЕРЕПОДКЛЮЧЕНИЕ';
    clearTimeout(crashReconnect);crashReconnect=setTimeout(connectCrash,2500);
  };
  crashSocket.onerror=()=>crashSocket.close();
}
connectCrash();


/* Учебный банк: никакого реального денежного счёта. Все изменения — через API. */
document.querySelectorAll('[data-bank]').forEach(button=>button.addEventListener('click',async()=>{
  button.disabled=true;
  try {
    const action=button.dataset.bank;
    const amount=action==='refresh'?0:Number($('bank-amount').value);
    if(action!=='refresh'&&(!Number.isInteger(amount)||amount<1)){toast('Введи целую сумму больше нуля');return;}
    const data=await request('/api/bank',{action,amount});
    if(profile){profile.points=data.points;profile.bank_points=data.bank_points;profile.bank_rate=data.bank_rate;paint(profile);}
    $('bank-next').textContent=`Следующее начисление: ${new Date(data.next_update*1000).toLocaleTimeString('ru-RU')}`;
    toast(action==='deposit'?'Игровые ₽ помещены в банк':action==='withdraw'?'Игровые ₽ возвращены в баланс':'Баланс банка обновлён');
  }catch(e){toast(e.message);}finally{button.disabled=false;}
}));
$('admin-save').addEventListener('click',async()=>{
 try {
  const target_id=Number($('admin-target').value),rate=Number($('admin-rate').value);
  if(!Number.isSafeInteger(target_id)||target_id<=0||!Number.isFinite(rate)){toast('Проверь ID и процент');return;}
  const result=await request('/api/admin/bank-rate',{target_id,rate});
  toast(`Для ID ${result.target_id} установлено ${result.bank_rate}%`);
 }catch(e){toast(e.message);}
});

/* Справочный Bitcoin API: только чтение цен; никакой торговли. */
async function loadBtc(){
 try {
  const res=await fetch('/api/market/btc');const data=await res.json();
  if(!data.price_rub)throw new Error(data.error||'Нет котировки');
  $('btc-price').textContent=`${Number(data.price_rub).toLocaleString('ru-RU')} ₽ / BTC`;
  const delta=Number(data.change_24h);
  $('btc-trend').textContent=Number.isFinite(delta)?`${delta>=0?'↗':'↘'} ${delta.toFixed(2)}% / 24 ч`:'—';
  $('btc-trend').classList.toggle('negative',delta<0);
  $('btc-updated').textContent=`${data.source} · ${data.as_of?new Date(data.as_of*1000).toLocaleString('ru-RU'):''}${data.stale?' · данные устарели':''}`;
 }catch(e){$('btc-price').textContent='Курс временно недоступен';$('btc-updated').textContent=e.message;}
}
$('btc-refresh').addEventListener('click',loadBtc);
loadBtc();setInterval(loadBtc,90000);
