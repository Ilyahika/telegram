"""Viva Fishing. Virtual fishing with server-side inventory and coin purchases.

Coins are earned in game; no real money payments or withdrawals.
All changes are inside SQLite IMMEDIATE transactions to prevent double-claiming.
"""
from __future__ import annotations

import hashlib
import json
import uuid
import math
import random
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from catalog_v5 import expand, AVATARS
from fishing_engine import loadout, create_battle, advance, target_at

from auth import current_user
from community import attempt_state,spend_attempt,reward_state
from config import ADMIN_ID
from db import session

router = APIRouter(prefix='/api/fishing', tags=['fishing'])
RNG = random.SystemRandom()
COOLDOWN_SECONDS = 0

RARITIES = dict(common='🖤 Обычный', rare='💙 Редкий', improved='🩵 Улучшенный', epic='💜 Эпический', legendary='💛 Легендарный', mythic='❤️ Мифический', absolute='🤍 Абсолютный')
TIERS = list(RARITIES)

LOCATIONS = [
    {'key':'pond', 'name':'Пруд', 'icon':'🌿', 'subtitle':'Тихий берег', 'description':'Караси, окуни и золотой карп', 'color':'#6dba8a'},
    {'key':'lake', 'name':'Озеро', 'icon':'🏞️', 'subtitle':'Глубокая вода', 'description':'Судак, щука и озёрный призрак', 'color':'#4aaeca'},
    {'key':'sea', 'name':'Море', 'icon':'🌅', 'subtitle':'Солёный прибой', 'description':'Тунец и морские редкости', 'color':'#58bce3'},
    {'key':'ocean', 'name':'Океан', 'icon':'🌊', 'subtitle':'Дальние глубины', 'description':'Марлин и глубинный левиафан', 'color':'#347dbe'},
    {'key':'stream', 'name':'Секретный ручей', 'icon':'✨', 'subtitle':'Таинственное течение', 'description':'Лунный угорь и кристальный карп', 'color':'#b88aee'},
]

# 20 distinct collectible fish: 4 per location. Rarity weights are intentionally
# displayed in the UI; there are no paid rolls or financial stakes.
FISH = [
    {'key':'crucian', 'name':'Карась', 'location':'pond', 'rarity':'common', 'icon':'🐟', 'weight':45, 'value':18},
    {'key':'perch', 'name':'Окунь', 'location':'pond', 'rarity':'common', 'icon':'🐟', 'weight':32, 'value':24},
    {'key':'carp', 'name':'Карп', 'location':'pond', 'rarity':'rare', 'icon':'🐠', 'weight':18, 'value':75},
    {'key':'gold_carp', 'name':'Золотой карп', 'location':'pond', 'rarity':'epic', 'icon':'🐠', 'weight':5, 'value':230},
    {'key':'bream', 'name':'Лещ', 'location':'lake', 'rarity':'common', 'icon':'🐟', 'weight':45, 'value':26},
    {'key':'zander', 'name':'Судак', 'location':'lake', 'rarity':'rare', 'icon':'🐟', 'weight':33, 'value':90},
    {'key':'pike', 'name':'Щука', 'location':'lake', 'rarity':'epic', 'icon':'🐠', 'weight':17, 'value':260},
    {'key':'lake_ghost', 'name':'Озёрный призрак', 'location':'lake', 'rarity':'secret', 'icon':'👻', 'weight':5, 'value':1200},
    {'key':'sardine', 'name':'Сардина', 'location':'sea', 'rarity':'common', 'icon':'🐟', 'weight':45, 'value':32},
    {'key':'mackerel', 'name':'Скумбрия', 'location':'sea', 'rarity':'rare', 'icon':'🐟', 'weight':32, 'value':110},
    {'key':'tuna', 'name':'Тунец', 'location':'sea', 'rarity':'marine', 'icon':'🐬', 'weight':18, 'value':420},
    {'key':'seahorse', 'name':'Морской конёк', 'location':'sea', 'rarity':'epic', 'icon':'🐠', 'weight':5, 'value':310},
    {'key':'clownfish', 'name':'Рыба-клоун', 'location':'ocean', 'rarity':'rare', 'icon':'🐠', 'weight':42, 'value':130},
    {'key':'swordfish', 'name':'Рыба-меч', 'location':'ocean', 'rarity':'epic', 'icon':'🐟', 'weight':33, 'value':360},
    {'key':'marlin', 'name':'Марлин', 'location':'ocean', 'rarity':'marine', 'icon':'🐬', 'weight':20, 'value':650},
    {'key':'leviathan', 'name':'Глубинный левиафан', 'location':'ocean', 'rarity':'secret', 'icon':'🐉', 'weight':5, 'value':2600},
    {'key':'trout', 'name':'Форель', 'location':'stream', 'rarity':'rare', 'icon':'🐟', 'weight':45, 'value':180},
    {'key':'grayling', 'name':'Радужный хариус', 'location':'stream', 'rarity':'epic', 'icon':'🌈', 'weight':31, 'value':530},
    {'key':'moon_eel', 'name':'Лунный угорь', 'location':'stream', 'rarity':'secret', 'icon':'🌙', 'weight':19, 'value':1600},
    {'key':'crystal_carp', 'name':'Кристальный карп', 'location':'stream', 'rarity':'secret', 'icon':'💎', 'weight':5, 'value':3200},
]

FINDS = [
    {'key':'driftwood', 'name':'Коряга', 'rarity':'common', 'icon':'🪵'},
    {'key':'shell', 'name':'Перламутровая ракушка', 'rarity':'rare', 'icon':'🐚'},
    {'key':'old_coin', 'name':'Старинная монета', 'rarity':'rare', 'icon':'🪙'},
    {'key':'pearl', 'name':'Жемчужина', 'rarity':'epic', 'icon':'⚪'},
    {'key':'anchor', 'name':'Забытый якорь', 'rarity':'marine', 'icon':'⚓'},
    {'key':'relic', 'name':'Реликвия глубин', 'rarity':'secret', 'icon':'🔮'},
    {'key':'gold_compass', 'name':'Золотой компас', 'rarity':'exclusive', 'icon':'🧭'},
    {'key':'gold_crown', 'name':'Золотая корона', 'rarity':'exclusive', 'icon':'👑'},
]

GEAR = [
    {'key':'starter_rod', 'type':'rod', 'name':'Бамбуковая удочка', 'rarity':'common', 'icon':'🎣', 'luck':0},
    {'key':'river_rod', 'type':'rod', 'name':'Речная удочка', 'rarity':'rare', 'icon':'🎣', 'luck':0.15},
    {'key':'carbon_rod', 'type':'rod', 'name':'Карбоновый спиннинг', 'rarity':'epic', 'icon':'🎣', 'luck':0.3},
    {'key':'sea_rod', 'type':'rod', 'name':'Морской трезубец', 'rarity':'marine', 'icon':'🔱', 'luck':0.45},
    {'key':'shadow_rod', 'type':'rod', 'name':'Удочка тёмных вод', 'rarity':'secret', 'icon':'🎣', 'luck':0.7},
    {'key':'gold_rod', 'type':'rod', 'name':'Золотая удочка', 'rarity':'exclusive', 'icon':'✨', 'luck':1.0},
    {'key':'starter_lure', 'type':'tackle', 'name':'Простая приманка', 'rarity':'common', 'icon':'🪝', 'luck':0},
    {'key':'silver_hook', 'type':'tackle', 'name':'Серебряный крючок', 'rarity':'rare', 'icon':'🪝', 'luck':0.12},
    {'key':'flash_spinner', 'type':'tackle', 'name':'Мерцающая блесна', 'rarity':'epic', 'icon':'✨', 'luck':0.25},
    {'key':'coral_float', 'type':'tackle', 'name':'Коралловый поплавок', 'rarity':'marine', 'icon':'🪸', 'luck':0.4},
    {'key':'phantom_lure', 'type':'tackle', 'name':'Призрачная приманка', 'rarity':'secret', 'icon':'🔮', 'luck':0.6},
    {'key':'gold_hook', 'type':'tackle', 'name':'Золотой крючок', 'rarity':'exclusive', 'icon':'🏆', 'luck':0.9},
]

# Existing identifiers are retained so inventories survive the upgrade.
for item in FISH + FINDS + GEAR:
    item['rarity'] = {'marine':'legendary','secret':'mythic','exclusive':'absolute'}.get(item['rarity'],item['rarity'])
for i, loc in enumerate(LOCATIONS): loc['level'] = [1,5,10,18,25][i]
FISH_BY_SPECIAL = {'carp':'improved','crystal_carp':'absolute','leviathan':'absolute'}
for fish in FISH: fish['rarity'] = FISH_BY_SPECIAL.get(fish['key'],fish['rarity'])
rod_names = ['Простая удочка','Бамбуковая удочка','Улучшенная удочка','Простой спиннинг','Улучшенный спиннинг','Спортивный спиннинг']
for i, item in enumerate(GEAR[:6]): item.update(name=rod_names[i],rarity=TIERS[i],price=[0,150,600,1800,5000,14000][i])
for item in GEAR[6:]: item.update(type='bait',price=200*(TIERS.index(item['rarity'])+1)**2)
GEAR.append(dict(key='bait_improved',type='bait',name='Силиконовая приманка',icon='🪝',rarity='improved',luck=.18,price=450))
for typ, title, icon in [('reel','Катушка','⚙️'),('line','Леска','🧵'),('spoon','Колебалка','🥄'),('spinner','Вертушка','🌀')]:
    for i, rarity in enumerate(TIERS):
        GEAR.append(dict(key=f'{typ}_{rarity}',type=typ,name=f'{title} · {RARITIES[rarity][2:]}',icon=icon,rarity=rarity,luck=i*.08,price=100*(i+1)**3))
CASES = []
for i,(key,name,price) in enumerate([('shore','Береговой',300),('lake','Озёрный',1200),('marine','Морской',4500),('secret','Глубинный',12000)]):
    pool=[g for g in GEAR if max(0,i-1)<=TIERS.index(g['rarity'])<=min(6,i+3)]
    weights=[max(1,70//(1+TIERS.index(g['rarity']))**2) for g in pool]
    CASES.append(dict(key=key,name=name+' кейс',icon='📦',price=price,items=[g['key'] for g in pool],weights=weights))

expand(FISH,GEAR,CASES,TIERS,LOCATIONS)
from catalog_v11 import upgrade, RARITIES, TIERS
upgrade(FISH,GEAR,CASES,LOCATIONS)
from catalog_v12 import apply_art
apply_art(FISH)
FINDS=[]

# Функция level_info: см. параметры, описание и вызовы ниже.
def level_info(xp):
    level=1; need=100; rest=xp
    while rest>=need:
        rest-=need; level+=1; need=100+50*(level-1)
    return dict(level=level,xp=xp,level_xp=rest,next_xp=need)

FISH_BY_ID = {r['key']: r for r in FISH}
FINDS_BY_ID = {r['key']: r for r in FINDS}
GEAR_BY_ID = {r['key']: r for r in GEAR}
LOC_BY_ID = {r['key']: r for r in LOCATIONS}
CASE_BY_ID = {r['key']: r for r in CASES}


# Функция effective_cases: см. параметры, описание и вызовы ниже.
def effective_cases(db):
    overrides={r['case_key']:json.loads(r['config']) for r in db.execute('SELECT case_key,config FROM fishing_case_settings')}
    result=[]
    for case in CASES:
        item={**case,'enabled':True,**overrides.get(case['key'],{})}
        if any(k not in GEAR_BY_ID or GEAR_BY_ID[k]['type']!=case['type'] for k in item['items']):item={**case,'enabled':True}
        item['revision']=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()[:16]
        result.append(item)
    return result


# Функция ensure_fishing: см. параметры, описание и вызовы ниже.
def ensure_fishing(db,uid):
    created=db.execute('INSERT OR IGNORE INTO fishing_progress (telegram_id) VALUES (?)',(uid,)).rowcount
    if created:
        add_item(db,'fishing_gear',uid,'starter_rod')
        add_item(db,'fishing_gear',uid,'starter_lure')
    from features_v11 import migrate_inventory
    migrate_inventory(db,uid)

# Функция buff_state: см. параметры, описание и вызовы ниже.
def buff_state(db,uid):
    r=db.execute('SELECT * FROM fishing_buffs WHERE telegram_id=?',(uid,)).fetchone()
    active=bool(r and r['expires_at']>time.time() and r['multiplier']>1)
    return dict(active=active,multiplier=r['multiplier'] if active else 1,expires_at=r['expires_at'] if r else 0,boost_from='epic')

# Функция weighted_cases: см. параметры, описание и вызовы ниже.
def weighted_cases(db,uid):
    buff=buff_state(db,uid);result=[]
    for base in effective_cases(db):
        c={**base};c['weights']=[w*(buff['multiplier'] if TIERS.index(GEAR_BY_ID[k]['rarity'])>=2 else 1) for k,w in zip(c['items'],c['weights'])]
        c['revision']=hashlib.sha256((base['revision']+':'+str(buff['multiplier'])).encode()).hexdigest()[:16]
        result.append(c)
    return result

# Функция fish_pool: см. параметры, описание и вызовы ниже.
def fish_pool(location,equipment,buff):
    stats=loadout(equipment,GEAR_BY_ID);choices=[f for f in FISH if f['location']==location]
    weights=[f['weight']*(1+stats.get('luck',0)*TIERS.index(f['rarity'])*.6)*(buff['multiplier'] if TIERS.index(f['rarity'])>=2 else 1) for f in choices]
    return choices,weights

# Функция active_battle: см. параметры, описание и вызовы ниже.
def active_battle(db,uid):
    r=db.execute('SELECT * FROM fishing_sessions WHERE telegram_id=? AND finished=0',(uid,)).fetchone()
    if not r:return None
    b=json.loads(r['payload'])
    if b.get('version')!=11:
        p=db.execute('SELECT * FROM fishing_progress WHERE telegram_id=?',(uid,)).fetchone();equipment={k:p[k] for k in ['rod','tackle','reel']}
        fish=FISH_BY_ID[b['fish']['key']]
        b=create_battle(fish,b['kg'],equipment,loadout(equipment,GEAR_BY_ID),b['seed'],b['id'],time.time(),TIERS.index(fish['rarity']))
        db.execute('UPDATE fishing_sessions SET payload=? WHERE telegram_id=?',(json.dumps(b),uid))
    return b


# Функция inventory: см. параметры, описание и вызовы ниже.
def inventory(db, table: str, uid: int, catalog: dict):
    return [{**catalog[r['item_key']], 'amount':r['amount']} for r in db.execute(
        f'SELECT item_key, amount FROM {table} WHERE telegram_id=? AND amount>0', (uid,))
        if r['item_key'] in catalog]


# Функция snapshot: см. параметры, описание и вызовы ниже.
def snapshot(db, uid: int) -> dict:
    p = db.execute('SELECT * FROM fishing_progress WHERE telegram_id=?', (uid,)).fetchone()
    caught = p['catches']
    gear = [dict(GEAR_BY_ID[r['gear_key']], amount=r['amount']) for r in db.execute(
        'SELECT gear_key,amount FROM fishing_gear WHERE telegram_id=? AND amount>0', (uid,))
        if r['gear_key'] in GEAR_BY_ID]
    opened = {r['case_key']:r['opened'] for r in db.execute('SELECT case_key,opened FROM fishing_cases WHERE telegram_id=?', (uid,))}
    amounts={r['case_key']:r['amount'] for r in db.execute('SELECT case_key,amount FROM fishing_cases WHERE telegram_id=?',(uid,))}
    cases = [{**c,'amount':amounts.get(c['key'],0),'opened':opened.get(c['key'],0),'rewards':[{**GEAR_BY_ID[k],'chance':w/sum(c['weights'])*100,'duplicate_sale':duplicate_value(c,GEAR_BY_ID[k])} for k,w in zip(c['items'],c['weights'])]} for c in weighted_cases(db,uid)]
    player = dict(db.execute('SELECT p.*,b.avatar,b.blocked,b.reason,b.last_seen FROM players p JOIN bh b USING(telegram_id) WHERE telegram_id=?',(uid,)).fetchone())
    active=active_battle(db,uid)
    equipment={k:p[k] for k in ['rod','tackle','reel']}
    buff=buff_state(db,uid)
    odds={}
    for loc in LOCATIONS:
        pool,weights=fish_pool(loc['key'],equipment,buff);total=sum(weights)
        odds[loc['key']]=[{**f,'chance':w/total*100} for f,w in zip(pool,weights)]
    return {
        **__import__('features_v11').extra_state(db,uid),'attempts':attempt_state(db,uid),'rewards':reward_state(db,uid),'location_records':{r['location']:{'fish':FISH_BY_ID.get(r['fish_key'],{}).get('name','Рыба'),'rarity':r['rarity'],'kg':r['kg']} for r in db.execute('SELECT location,fish_key,rarity,kg FROM viva_location_records WHERE telegram_id=?',(uid,))},'best_kg':db.execute('SELECT COALESCE(MAX(kg),0) FROM fishing_catch_history WHERE telegram_id=?',(uid,)).fetchone()[0], 'player':player, 'level':level_info(p['xp']), 'active':active,'buff':buff,'loadout':loadout(equipment,GEAR_BY_ID),'fish_odds':odds, 'server_time':time.time(),
        'progress': {'xp':p['xp'], 'equipment':{k:p[k] for k in ['rod','tackle','reel']}, 'casts':p['casts'], 'catches':caught, 'last_cast':p['last_cast'],
                     'cooldown_seconds':COOLDOWN_SECONDS, 'rod':p['rod'], 'tackle':p['tackle']},
        'fish': inventory(db, 'fishing_fish', uid, FISH_BY_ID),
        'finds': inventory(db, 'fishing_finds', uid, FINDS_BY_ID),
        'discovered': [r[0] for r in db.execute('SELECT fish_key FROM fishing_discovered WHERE telegram_id=?', (uid,))],
        'gear': gear, 'cases':cases, 'locations':LOCATIONS,
        'catalog': {'fish':FISH, 'finds':FINDS, 'gear':GEAR, 'rarities':RARITIES,'avatars':AVATARS},
    }


# Функция add_item: см. параметры, описание и вызовы ниже.
def add_item(db, table: str, uid: int, key: str):
    col = 'gear_key' if table == 'fishing_gear' else 'item_key'
    db.execute(f'''INSERT INTO {table} (telegram_id,{col},amount) VALUES (?,?,1)
                 ON CONFLICT(telegram_id,{col}) DO UPDATE SET amount=amount+1''', (uid,key))


# Функция fishing_state: см. параметры, описание и вызовы ниже.
@router.get('/state')
def fishing_state(user: dict=Depends(current_user)):
    with session(write=True) as db:
        ensure_fishing(db,user['id'])
        return snapshot(db,user['id'])


# Класс Cast: см. параметры, описание и вызовы ниже.
class Cast(BaseModel):
    location: str


# Функция cast: см. параметры, описание и вызовы ниже.
@router.post('/cast')
def cast(data:Cast,user:dict=Depends(current_user)):
    if data.location not in LOC_BY_ID:raise HTTPException(400,'Нет локации')
    now=time.time();uid=user['id']
    with session(write=True) as db:
        ensure_fishing(db,uid);row=db.execute('SELECT * FROM fishing_progress WHERE telegram_id=?',(uid,)).fetchone()
        active=active_battle(db,uid)
        if active:return {'battle':active,'state':snapshot(db,uid)}
        if level_info(row['xp'])['level']<LOC_BY_ID[data.location]['level']:raise HTTPException(403,'Недостаточный уровень')
        if now-row['last_cast']<COOLDOWN_SECONDS:raise HTTPException(429,f"Следующий заброс через {math.ceil(COOLDOWN_SECONDS-(now-row['last_cast']))} сек.")
        if db.execute("SELECT COUNT(*) FROM catches_v11 WHERE telegram_id=? AND place='bag'",(uid,)).fetchone()[0]>=30:raise HTTPException(409,'Подсак заполнен: 30 рыб')
        for slot in ['rod','reel','tackle']:
            owned=db.execute('SELECT amount FROM fishing_gear WHERE telegram_id=? AND gear_key=?',(uid,row[slot])).fetchone()
            if not owned or owned[0]<1:raise HTTPException(409,'Нужны удочка, катушка и приманка. Выбери их в рюкзаке.')
        equipment={k:row[k] for k in ['rod','tackle','reel']};stats=loadout(equipment,GEAR_BY_ID)
        required=LOC_BY_ID[data.location]['required_kg']
        if any(GEAR_BY_ID.get(k,{}).get('max_kg',0)<required for k in equipment.values()):raise HTTPException(409,f'Для этой локации каждый предмет должен выдерживать {required:g} кг')
        pool,weights=fish_pool(data.location,equipment,buff_state(db,uid));fish=RNG.choices(pool,weights=weights,k=1)[0]
        kg=round(RNG.uniform(fish['min_kg'],fish['max_kg']),3)
        battle=create_battle(fish,kg,equipment,stats,RNG.random()*6.28,uuid.uuid4().hex,now,TIERS.index(fish['rarity']))
        spend_attempt(db,uid)
        db.execute('INSERT OR REPLACE INTO fishing_sessions VALUES (?,?,?,?,0)',(uid,battle['id'],json.dumps(battle),now+86400))
        db.execute('UPDATE fishing_progress SET casts=casts+1,last_cast=? WHERE telegram_id=?',(int(now),uid))
        return {'battle':battle,'state':snapshot(db,uid)}

# Класс Tick: см. параметры, описание и вызовы ниже.
class Tick(BaseModel):
    id:str
    position:float=Field(ge=0,le=1)
    sequence:int=Field(ge=0)
    reeling:bool=True
    hook:bool=False

# Функция tick: см. параметры, описание и вызовы ниже.
@router.post('/tick')
def tick(data:Tick,user:dict=Depends(current_user)):
    uid=user['id'];now=time.time()
    with session(write=True) as db:
        r=db.execute('SELECT * FROM fishing_sessions WHERE telegram_id=? AND session_id=?',(uid,data.id)).fetchone()
        if not r:raise HTTPException(404,'Заброс не найден')
        b=json.loads(r['payload'])
        if r['finished']:return dict(done=True,won=b.get('won',False),score=b.get('progress',0),battle=b,state=snapshot(db,uid))
        if not math.isfinite(data.position):raise HTTPException(400,'Некорректное положение')
        b=active_battle(db,uid)
        advance(b,now,data.position,data.reeling,data.hook,data.sequence)
        if b['done']:
            if b['won']:
                fish=b['fish'];add_item(db,'fishing_fish',uid,fish['key'])
                db.execute("INSERT INTO catches_v11(telegram_id,fish_key,kg,place) VALUES (?,?,?,'bag')",(uid,fish['key'],b['kg']))
                db.execute('INSERT INTO fishing_catch_history(telegram_id,fish_key,kg,ts) VALUES (?,?,?,?)',(uid,fish['key'],b['kg'],int(now)))
                db.execute('INSERT OR IGNORE INTO fishing_discovered VALUES (?,?)',(uid,fish['key']))
                # Track the rarest caught fish per location, then heaviest within the same rarity.
                destination=fish['location']
                existing=db.execute('SELECT rarity,kg FROM viva_location_records WHERE telegram_id=? AND location=?',(uid,destination)).fetchone()
                if not existing or (TIERS.index(fish['rarity']), b['kg'])>(TIERS.index(existing['rarity']) if existing['rarity'] in TIERS else -1, existing['kg']):
                    db.execute('INSERT INTO viva_location_records(telegram_id,location,fish_key,rarity,kg,ts) VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id,location) DO UPDATE SET fish_key=excluded.fish_key,rarity=excluded.rarity,kg=excluded.kg,ts=excluded.ts',(uid,destination,fish['key'],fish['rarity'],b['kg'],int(now)))
                xp=25+TIERS.index(fish['rarity'])*20+int(b['kg']*2);b['xp']=xp
                db.execute('UPDATE fishing_progress SET catches=catches+1,xp=xp+? WHERE telegram_id=?',(xp,uid))
        db.execute('UPDATE fishing_sessions SET payload=?,finished=? WHERE telegram_id=?',(json.dumps(b),int(b['done']),uid))
        return dict(done=b['done'],won=b.get('won',False),target=b.get('target',.5),score=b['progress'],battle=b,state=snapshot(db,uid) if b['done'] else None)


# Класс Equip: см. параметры, описание и вызовы ниже.
class Equip(BaseModel):
    gear_key: str


# Функция equip: см. параметры, описание и вызовы ниже.
@router.post('/equip')
def equip(data:Equip,user:dict=Depends(current_user)):
    gear = GEAR_BY_ID.get(data.gear_key)
    if not gear:
        raise HTTPException(400, 'Нет такого предмета')
    with session(write=True) as db:
        ensure_fishing(db,user['id'])
        owned = db.execute('SELECT amount FROM fishing_gear WHERE telegram_id=? AND gear_key=?',
                           (user['id'],data.gear_key)).fetchone()
        if not owned or owned['amount'] < 1:
            raise HTTPException(403, 'Этот предмет не найден в рюкзаке')
        db.execute(f'UPDATE fishing_progress SET {"tackle" if gear["type"]=="bait" else gear["type"]}=? WHERE telegram_id=?',
                   (data.gear_key,user['id']))
        return {'state':snapshot(db,user['id'])}


# Класс CaseOpen: см. параметры, описание и вызовы ниже.
class CaseOpen(BaseModel):
    case_key:str
    revision:str|None=None
    count:int=Field(default=1,ge=1,le=5)

# Функция open_case: см. параметры, описание и вызовы ниже.
@router.post('/case/open')
def open_case(data:CaseOpen,user:dict=Depends(current_user)):
    if data.count not in (1,3,5):raise HTTPException(400,'Выбери 1, 3 или 5')
    with session(write=True) as db:
        uid=user['id'];ensure_fishing(db,uid)
        case=next((c for c in weighted_cases(db,uid) if c['key']==data.case_key),None)
        if not case or not case['enabled']:raise HTTPException(409,'Кейс недоступен')
        if data.revision and data.revision!=case['revision']:raise HTTPException(409,'Состав кейса изменился')
        owned=db.execute('SELECT amount FROM fishing_cases WHERE telegram_id=? AND case_key=?',(uid,data.case_key)).fetchone()
        free=min(data.count,owned[0] if owned else 0);cost=(data.count-free)*case['price']
        if db.execute('SELECT coins FROM players WHERE telegram_id=?',(uid,)).fetchone()[0]<cost:raise HTTPException(409,'Недостаточно долларов')
        # No automatic selling: require enough space in the correct equipment category.
        category=case['type']
        occupied=db.execute('SELECT COALESCE(SUM(amount),0) FROM fishing_gear WHERE telegram_id=? AND gear_key IN ('+','.join('?' for _ in [g for g in GEAR if g['type']==category])+')',(uid,*[g['key'] for g in GEAR if g['type']==category])).fetchone()[0]
        if occupied+data.count>6:raise HTTPException(409,'Недостаточно места: максимум 6 предметов этого типа. Освободи место перед открытием')
        db.execute('UPDATE players SET coins=coins-? WHERE telegram_id=?',(cost,uid))
        if free:db.execute('UPDATE fishing_cases SET amount=amount-? WHERE telegram_id=? AND case_key=?',(free,uid,data.case_key))
        rewards=[]
        for _ in range(data.count):
            g=GEAR_BY_ID[RNG.choices(case['items'],weights=case['weights'])[0]]
            add_item(db,'fishing_gear',uid,g['key'])
            rewards.append(dict(reward=g,auto_sold=False,compensation=0))
        db.execute('UPDATE fishing_progress SET xp=xp+? WHERE telegram_id=?',(35*data.count,uid))
        db.execute('INSERT INTO fishing_cases(telegram_id,case_key,opened) VALUES (?,?,?) ON CONFLICT(telegram_id,case_key) DO UPDATE SET opened=opened+excluded.opened',(uid,data.case_key,data.count))
        return dict(rewards=rewards,state=snapshot(db,uid))


# Класс SellFish: см. параметры, описание и вызовы ниже.
class SellFish(BaseModel):
    fish_key: str='all'


# Функция sell_fish: см. параметры, описание и вызовы ниже.
@router.post('/sell')
def sell_fish(data:SellFish,user:dict=Depends(current_user)):
    if data.fish_key != 'all' and not data.fish_key.isdigit() and data.fish_key not in FISH_BY_ID:
        raise HTTPException(400,'Неизвестная рыба')
    from features_v11 import sell_catches
    return sell_catches(data.fish_key,user['id'])

# Функция buy: см. параметры, описание и вызовы ниже.
@router.post('/buy')
def buy(data:Equip,user:dict=Depends(current_user)):
    raise HTTPException(403,'Оснастка доступна только в кейсах')


# Функция duplicate_value: см. параметры, описание и вызовы ниже.
def duplicate_value(case,gear):
    return gear['sell_price']

# Класс ProfileChange: см. параметры, описание и вызовы ниже.
class ProfileChange(BaseModel):
    nickname:str=Field(min_length=3,max_length=24)
    avatar:str
    color:str="#4aaeca"

# Функция change_profile: см. параметры, описание и вызовы ниже.
@router.post('/profile')
def change_profile(data:ProfileChange,user:dict=Depends(current_user)):
    nickname=data.nickname.strip()
    if len(nickname)<3 or any(not c.isprintable() or c in '<>' for c in nickname):raise HTTPException(400,'Ник: 3–24 символа без переносов и угловых скобок')
    if data.avatar not in AVATARS:raise HTTPException(400,'Выбери аватар из списка')
    if not __import__('re').fullmatch(r'#[0-9a-fA-F]{6}',data.color):raise HTTPException(400,'Неверный цвет')
    with session(write=True) as db:
        ensure_fishing(db,user['id'])
        db.execute('UPDATE profiles_v11 SET color=? WHERE telegram_id=?',(data.color,user['id']))
        db.execute('UPDATE players SET nickname=? WHERE telegram_id=?',(nickname,user['id']))
        db.execute('UPDATE bh SET avatar=? WHERE telegram_id=?',(data.avatar,user['id']))
        return {'state':snapshot(db,user['id'])}

# Функция luck_status: см. параметры, описание и вызовы ниже.
@router.get('/luck')
def luck_status(user:dict=Depends(current_user)):
    with session() as db:return buff_state(db,user['id'])
