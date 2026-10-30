'use strict';
const tg=window.Telegram?.WebApp;
const initData=tg?.initData || '';
let gameData=null, gameCatalog=null, currentPage='';
const rarityNames={common:'Обычный',rare:'Редкий',epic:'Эпический',legendary:'Легендарный',mythic:'Мифический',exclusive:'Эксклюзивный'};
const rarityColors={common:'#aeb9c5',rare:'#68aaff',epic:'#b78afa',legendary:'#ffc16b',mythic:'#ff7299',exclusive:'#e6c7ff'};
const overlay=document.getElementById('featureOverlay');
const content=document.getElementById('overlayContent');
const title=document.getElementById('overlayTitle');
const status=document.createElement('div');status.className='auth-status';document.querySelector('.dev-note').replaceWith(status);
async function request(path,opts={}){
  const response=await fetch(path,{...opts,headers:{'Content-Type':'application/json',...(initData?{'X-Telegram-Init-Data':initData}:{}),...(opts.headers||{})}});
  const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Ошибка сервера');return data;
}
function syncProfile(){
 if(!gameData)return;
 const p=gameData.player;
 document.getElementById('playerName').textContent=p.nickname;
 document.getElementById('coinBalance').textContent=p.coins.toLocaleString('ru-RU');
 document.getElementById('crystalBalance').textContent=p.crystals.toLocaleString('ru-RU');
 const companion=gameData.inventory[0];
 if(companion){window.setCompanionSprite?.(companion.icon);document.querySelector('.companion-portrait').innerHTML=`<img alt="" src="${companion.icon}">`;document.querySelector('.companion-info h3').textContent=companion.name+' · '+companion.rarity_name;document.querySelector('.companion-info p').textContent='Следует за тобой по острову';}
 else {document.querySelector('.companion-info h3').textContent='Спутник не выбран';document.querySelector('.companion-info p').textContent='Открой кейс и найди первого монстра';document.querySelector('.companion-portrait').textContent='🥚';}
 status.textContent=gameData.demo?'⚙️ Деморежим: отдельный тестовый профиль · данные сохраняются':'✅ Telegram-аккаунт подключён · данные сохраняются';
}
function drawCases(){
 title.textContent='🎁 Кейсы монстров';content.innerHTML='<p class="hint">Каждый кейс содержит одного случайного монстра. Все награды и вероятность редкостей показаны до открытия. Для проверки доступны стартовые 1 200 монет.</p><div id="rewardBox" class="reward-box"></div><div class="case-list" id="caseList"></div>';
 const list=document.getElementById('caseList');
 gameCatalog.cases.forEach(c=>{
  const cell=document.createElement('article');cell.className='case-tile';
  const chance=Object.entries(c.chances).map(([r,n])=>`${rarityNames[r]} ${n}%`).join(' · ');
  cell.innerHTML=`<div class="case-art">${({forest:'🌿',magic:'🔮',ancient:'📦',star:'🌟'})[c.id]}</div><h3>${c.name}</h3><p>🪙 ${c.price.toLocaleString('ru-RU')}</p><div class="case-probs">${chance}</div><button type="button">Открыть кейс</button>`;
  const button=cell.querySelector('button');button.disabled=gameData.player.coins<c.price;
  button.addEventListener('click',async()=>{button.disabled=true;button.textContent='Открываем...';try{const answer=await request('/api/cases/open',{method:'POST',body:JSON.stringify({case_id:c.id})});gameData.player=answer.player;gameData.inventory.unshift(answer.reward);syncProfile();const box=document.getElementById('rewardBox');box.classList.add('show');box.innerHTML=`<img src="${answer.reward.portrait}" alt=""><h3>${answer.reward.name}</h3><p style="color:${rarityColors[answer.reward.rarity]}">${answer.reward.rarity_name}</p><p>Новый монстр добавлен в инвентарь!</p>`;box.scrollIntoView({behavior:'smooth',block:'start'});document.querySelectorAll('#caseList button').forEach((b,i)=>b.disabled=gameData.player.coins<gameCatalog.cases[i].price);}catch(error){showToast(error.message)}finally{button.textContent='Открыть кейс';button.disabled=gameData.player.coins<c.price}});
  list.appendChild(cell);
 });
}
function drawInventory(){
 title.textContent='🐲 Мои монстры';content.innerHTML=`<p class="hint">Коллекция: ${gameData.inventory.length} существ. Получить новых монстров можно из кейсов.</p><div class="monster-grid" id="monsterGrid"></div>`;
 const grid=document.getElementById('monsterGrid');
 if(!gameData.inventory.length){grid.innerHTML='<p class="hint">В инвентаре пока пусто. Открой первый кейс!</p>';return}
 for(const m of gameData.inventory){const cell=document.createElement('article');cell.className='monster-tile';cell.innerHTML=`<img src="${m.portrait}" alt="Монстр ${m.name}"><h3>${m.name}</h3><div class="rarity-name" style="color:${rarityColors[m.rarity]}">${m.rarity_name}</div><p>Стихия: ${m.element}</p><small>Бонус +${m.bonus}% · №${m.instance_id}</small>`;grid.appendChild(cell)}
}
function openView(name){
 currentPage=name;overlay.classList.add('active');overlay.scrollTop=0;document.body.style.overflow='hidden';
 if(!gameData||!gameCatalog){title.textContent='Загрузка';content.innerHTML='<p class="hint">Проверяем профиль...</p>';return}
 if(name==='Кейсы')drawCases();else if(name==='Монстры'||name==='Инвентарь')drawInventory();else if(name==='Профиль'){title.textContent='👤 Профиль';content.innerHTML=`<div class="profile-card"><h3>${gameData.player.nickname.replaceAll('<','&lt;')}</h3><p>Уровень: ${gameData.player.level}</p><p>🪙 ${gameData.player.coins.toLocaleString('ru-RU')} монет</p><p>🐲 Монстров: ${gameData.inventory.length}</p><p>Telegram ID: ${gameData.player.id}</p></div>`;}
 else{title.textContent=name;content.innerHTML='<p class="hint">Этот раздел появится в следующем обновлении. Кейсы и инвентарь уже работают!</p>'}
}
function closeView(){overlay.classList.remove('active');document.body.style.overflow='';currentPage=''}
document.getElementById('closeOverlay').addEventListener('click',closeView);
window.addEventListener('keydown',e=>{if(e.key==='Escape')closeView()});
document.querySelectorAll('[data-feature]').forEach(b=>{b.addEventListener('click',()=>{const name=b.dataset.feature;if(name!=='Остров'){openView(name)}} ,true)});
// Existing v0.1 listeners are still attached. Stop them from showing their placeholder toasts.
document.querySelectorAll('[data-feature]').forEach(b=>b.addEventListener('click',e=>{if(b.dataset.feature!=='Остров')e.stopImmediatePropagation()},true));
(async()=>{try{gameCatalog=await request('/api/catalog');gameData=await request('/api/auth',{method:'POST'});syncProfile();tg?.ready();tg?.expand();}catch(e){status.innerHTML=`<span class="demo-tag">⚠️ ${e.message}</span> · Запусти через Telegram или установи DEV_DEMO=1 только для локальной разработки.`;console.error(e)}})();
