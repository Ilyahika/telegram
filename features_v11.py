"""Individual catches, capped aquarium accrual, promotions and staff permissions."""
import time,re
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from auth import current_user,admin_user
from config import ADMIN_ID
from db import session
router=APIRouter(prefix='/api/v11')
PREFIXES=['😇 Бета тестер','🦾 Активный','👾 Разработчик','🫆 Модератор','🤵 Донатер']
SCHEMA='''
CREATE TABLE IF NOT EXISTS profiles_v11(telegram_id INTEGER PRIMARY KEY,color TEXT NOT NULL DEFAULT '#4aaeca',prefix TEXT NOT NULL DEFAULT '',moderator INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS catches_v11(id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,fish_key TEXT NOT NULL,kg REAL NOT NULL,place TEXT NOT NULL DEFAULT 'bag');
CREATE INDEX IF NOT EXISTS idx_v11_catch ON catches_v11(telegram_id,place);
CREATE TABLE IF NOT EXISTS tanks_v11(telegram_id INTEGER PRIMARY KEY,anchor REAL NOT NULL,deadline REAL NOT NULL,balance REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS promos_v11(code TEXT PRIMARY KEY,coins INTEGER NOT NULL,xp INTEGER NOT NULL,uses INTEGER NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS promo_claims_v11(code TEXT NOT NULL,telegram_id INTEGER NOT NULL,PRIMARY KEY(code,telegram_id));
CREATE TABLE IF NOT EXISTS notices_v11(id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,text TEXT NOT NULL,kind TEXT NOT NULL);
'''
# Функция migrate_inventory: см. параметры, описание и вызовы ниже.
def migrate_inventory(db,uid):
    from fishing import FISH_BY_ID,GEAR_BY_ID,add_item
    db.execute('INSERT OR IGNORE INTO profiles_v11(telegram_id) VALUES (?)',(uid,))
    db.execute('INSERT OR IGNORE INTO tanks_v11(telegram_id,anchor,deadline) VALUES (?,?,?)',(uid,time.time(),time.time()+18000))
    if not db.execute("INSERT OR IGNORE INTO fishing_migrations VALUES (?,'v11_inventory')",(uid,)).rowcount:return
    # Convert stacks without discarding existing catches. Historical weights are used when available.
    for r in db.execute('SELECT * FROM fishing_fish WHERE telegram_id=? AND amount>0',(uid,)).fetchall():
        f=FISH_BY_ID.get(r['item_key'])
        if not f:continue
        weights=[x[0] for x in db.execute('SELECT kg FROM fishing_catch_history WHERE telegram_id=? AND fish_key=? ORDER BY id DESC LIMIT ?',(uid,f['key'],r['amount']))]
        for i in range(r['amount']):db.execute("INSERT INTO catches_v11(telegram_id,fish_key,kg) VALUES (?,?,?)",(uid,f['key'],weights[i] if i<len(weights) else f['min_kg']))
    for r in db.execute('SELECT gear_key FROM fishing_gear WHERE telegram_id=?',(uid,)).fetchall():
        if r[0] not in GEAR_BY_ID:db.execute('DELETE FROM fishing_gear WHERE telegram_id=? AND gear_key=?',(uid,r[0]))
    add_item(db,'fishing_gear',uid,'reel_common')
    db.execute("UPDATE fishing_progress SET reel=CASE WHEN reel='' THEN 'reel_common' ELSE reel END,line='',spoon='',spinner='' WHERE telegram_id=?",(uid,))
    db.execute('DELETE FROM fishing_case_settings') if not db.execute("SELECT 1 FROM fishing_migrations WHERE telegram_id=0 AND version='v11_cases'").fetchone() else None
    db.execute("INSERT OR IGNORE INTO fishing_migrations VALUES (0,'v11_cases')")
    for old,new in [('lake','reel_0'),('marine','bait_1'),('secret','rod_2')]:
        row=db.execute('SELECT amount,opened FROM fishing_cases WHERE telegram_id=? AND case_key=?',(uid,old)).fetchone()
        if row:
            db.execute('INSERT INTO fishing_cases(telegram_id,case_key,amount,opened) VALUES (?,?,?,?) ON CONFLICT(telegram_id,case_key) DO UPDATE SET amount=amount+excluded.amount,opened=opened+excluded.opened',(uid,new,*row));db.execute('DELETE FROM fishing_cases WHERE telegram_id=? AND case_key=?',(uid,old))
# Функция fish_value: см. параметры, описание и вызовы ниже.
def fish_value(f,kg):return max(1,round(f['value']*kg))
# Функция catch_rows: см. параметры, описание и вызовы ниже.
def catch_rows(db,uid,place):
    from fishing import FISH_BY_ID,TIERS
    return [{**FISH_BY_ID[r['fish_key']],**dict(r),'value':fish_value(FISH_BY_ID[r['fish_key']],r['kg']),'hourly':round(fish_value(FISH_BY_ID[r['fish_key']],r['kg'])*.03,4)} for r in db.execute('SELECT * FROM catches_v11 WHERE telegram_id=? AND place=? ORDER BY id DESC',(uid,place)) if r['fish_key'] in FISH_BY_ID]
# Функция tank_state: см. параметры, описание и вызовы ниже.
def tank_state(db,uid):
    r=db.execute('SELECT * FROM tanks_v11 WHERE telegram_id=?',(uid,)).fetchone();fish=catch_rows(db,uid,'tank');rate=sum(f['hourly'] for f in fish);elapsed=max(0,min(time.time(),r['deadline'])-r['anchor'])
    return dict(fish=fish,rate=rate,balance=r['balance']+elapsed*rate/3600,anchor=r['anchor'],cap_at=r['deadline'],server_time=time.time())
# Функция settle: см. параметры, описание и вызовы ниже.
def settle(db,uid):
    s=tank_state(db,uid)
    # Preserve the original five-hour cutoff when changing occupants.
    db.execute('UPDATE tanks_v11 SET balance=?,anchor=? WHERE telegram_id=?',(s['balance'],time.time(),uid))
    return s

# Функция extra_state: см. параметры, описание и вызовы ниже.
def extra_state(db,uid):
    staff=dict(db.execute('SELECT * FROM profiles_v11 WHERE telegram_id=?',(uid,)).fetchone())
    return dict(catches=catch_rows(db,uid,'bag'),aquarium=tank_state(db,uid),profile=staff,role='admin' if uid==ADMIN_ID else 'moderator' if staff['moderator'] else 'player',prefixes=PREFIXES,notices=[dict(r) for r in db.execute('SELECT * FROM notices_v11 WHERE telegram_id=? ORDER BY id DESC LIMIT 10',(uid,))])

# Функция sell_catches: см. параметры, описание и вызовы ниже.
def sell_catches(key,uid):
    from fishing import snapshot
    with session(write=True) as db:
        rows=[f for f in catch_rows(db,uid,'bag') if key=='all' or str(f['id'])==key or f['key']==key]
        if not rows:raise HTTPException(409,'Нет рыбы для продажи')
        total=sum(f['value'] for f in rows)
        for f in rows:
            db.execute('DELETE FROM catches_v11 WHERE id=?',(f['id'],));db.execute('UPDATE fishing_fish SET amount=MAX(0,amount-1) WHERE telegram_id=? AND item_key=?',(uid,f['key']))
        db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(total,uid));return dict(earned=total,state=snapshot(db,uid))
# Класс TankAction: см. параметры, описание и вызовы ниже.
class TankAction(BaseModel):
    id:int=0
    action:str
# Функция tank: см. параметры, описание и вызовы ниже.
@router.post('/tank')
def tank(data:TankAction,user=Depends(current_user)):
    from fishing import ensure_fishing,snapshot
    uid=user['id']
    with session(write=True) as db:
        ensure_fishing(db,uid);s=tank_state(db,uid)
        if data.action=='claim':
            earned=int(s['balance']);db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(earned,uid));db.execute('UPDATE tanks_v11 SET anchor=?,deadline=?,balance=? WHERE telegram_id=?',(time.time(),time.time()+18000,s['balance']-earned,uid))
        elif data.action in ('add','remove'):
            place='bag' if data.action=='add' else 'tank';target='tank' if place=='bag' else 'bag'
            if not db.execute('SELECT 1 FROM catches_v11 WHERE id=? AND telegram_id=? AND place=?',(data.id,uid,place)).fetchone():raise HTTPException(404,'Рыба не найдена')
            reserved=1 if target=='bag' and db.execute('SELECT 1 FROM fishing_sessions WHERE telegram_id=? AND finished=0',(uid,)).fetchone() else 0
            if len(catch_rows(db,uid,target))+reserved>=(5 if target=='tank' else 30):raise HTTPException(409,'Все места заняты (одно место зарезервировано для текущего улова)')
            settle(db,uid)
            if data.action=='add' and not s['fish'] and s['balance']==0:
                db.execute('UPDATE tanks_v11 SET anchor=?,deadline=? WHERE telegram_id=?',(time.time(),time.time()+18000,uid))
            db.execute('UPDATE catches_v11 SET place=? WHERE id=?',(target,data.id))
        else:raise HTTPException(400,'Неизвестное действие')
        return dict(state=snapshot(db,uid))
# Класс GearSell: см. параметры, описание и вызовы ниже.
class GearSell(BaseModel):
    key:str
# Функция sell_gear: см. параметры, описание и вызовы ниже.
@router.post('/gear/sell')
def sell_gear(data:GearSell,user=Depends(current_user)):
    from fishing import GEAR_BY_ID,snapshot
    g=GEAR_BY_ID.get(data.key);uid=user['id']
    if not g:raise HTTPException(404,'Нет снасти')
    with session(write=True) as db:
        r=db.execute('SELECT amount FROM fishing_gear WHERE telegram_id=? AND gear_key=?',(uid,data.key)).fetchone()
        p=db.execute('SELECT * FROM fishing_progress WHERE telegram_id=?',(uid,)).fetchone();slot='tackle' if g['type']=='bait' else g['type']
        if not r or r[0]<=0:raise HTTPException(409,'Нет снасти')
        if r[0]==1 and p[slot]==data.key:raise HTTPException(409,'Сначала сними или замени снасть')
        db.execute('UPDATE fishing_gear SET amount=amount-1 WHERE telegram_id=? AND gear_key=?',(uid,data.key));db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(g['sell_price'],uid));return dict(state=snapshot(db,uid))
# Класс Promo: см. параметры, описание и вызовы ниже.
class Promo(BaseModel):
    code:str=Field(min_length=2,max_length=32)
# Функция promo: см. параметры, описание и вызовы ниже.
@router.post('/promo')
def promo(data:Promo,user=Depends(current_user)):
    from fishing import ensure_fishing,snapshot
    uid=user['id'];code=data.code.strip().upper()
    with session(write=True) as db:
        ensure_fishing(db,uid);r=db.execute('SELECT * FROM promos_v11 WHERE code=?',(code,)).fetchone()
        if not r or r['uses']<=0 or (r['expires'] and r['expires']<time.time()):raise HTTPException(409,'Промокод недоступен')
        if db.execute('SELECT 1 FROM promo_claims_v11 WHERE code=? AND telegram_id=?',(code,uid)).fetchone():raise HTTPException(409,'Промокод уже использован')
        db.execute('INSERT INTO promo_claims_v11 VALUES (?,?)',(code,uid));db.execute('UPDATE promos_v11 SET uses=uses-1 WHERE code=?',(code,));db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(r['coins'],uid));db.execute('UPDATE fishing_progress SET xp=xp+? WHERE telegram_id=?',(r['xp'],uid));return dict(state=snapshot(db,uid))
# Класс PromoCreate: см. параметры, описание и вызовы ниже.
class PromoCreate(Promo):
    coins:int=Field(ge=0,le=1000000000)
    xp:int=Field(default=0,ge=0,le=10000000)
    uses:int=Field(ge=1,le=1000000)
    hours:int=Field(default=168,ge=1,le=8760)
# Функция promo_create: см. параметры, описание и вызовы ниже.
@router.post('/admin/promo')
def promo_create(data:PromoCreate,admin=Depends(admin_user)):
    code=data.code.strip().upper()
    if not re.fullmatch('[A-Z0-9_-]{2,32}',code):raise HTTPException(400,'Код: латинские буквы, цифры, _ и -')
    with session(write=True) as db:
        if db.execute('SELECT 1 FROM promos_v11 WHERE code=?',(code,)).fetchone():raise HTTPException(409,'Этот код уже существует')
        db.execute('INSERT INTO promos_v11 VALUES (?,?,?,?,?)',(code,data.coins,data.xp,data.uses,time.time()+data.hours*3600))
    return dict(ok=True)
# Класс StaffChange: см. параметры, описание и вызовы ниже.
class StaffChange(BaseModel):
    uid:int
    prefix:str=''
    moderator:bool=False
# Функция staff_change: см. параметры, описание и вызовы ниже.
@router.post('/admin/staff')
def staff_change(data:StaffChange,admin=Depends(admin_user)):
    from fishing import ensure_fishing
    if data.prefix and data.prefix not in PREFIXES:raise HTTPException(400,'Неизвестный префикс')
    with session(write=True) as db:
        if not db.execute('SELECT 1 FROM players WHERE telegram_id=?',(data.uid,)).fetchone():raise HTTPException(404,'Нет игрока')
        ensure_fishing(db,data.uid);db.execute('UPDATE profiles_v11 SET prefix=?,moderator=? WHERE telegram_id=?',(data.prefix,int(data.moderator),data.uid))
        db.execute('INSERT INTO admin_log(ts,admin_id,target,action,value) VALUES (?,?,?,?,?)',(int(time.time()),admin['id'],data.uid,'staff',data.model_dump_json()))
    return dict(ok=True)
# Функция moderator_user: см. параметры, описание и вызовы ниже.
def moderator_user(user=Depends(current_user)):
    with session() as db:r=db.execute('SELECT moderator FROM profiles_v11 WHERE telegram_id=?',(user['id'],)).fetchone()
    if user['id']!=ADMIN_ID and not(r and r[0]):raise HTTPException(403,'Нет доступа')
    return user
# Функция players: см. параметры, описание и вызовы ниже.
@router.get('/players')
def players(q:str='',user=Depends(moderator_user)):
    with session() as db:return dict(players=[dict(r) for r in db.execute('SELECT p.telegram_id,p.nickname,p.telegram_name,p.coins,b.avatar,b.blocked FROM players p JOIN bh b USING(telegram_id) WHERE CAST(p.telegram_id AS TEXT) LIKE ? OR p.nickname LIKE ? OR p.telegram_name LIKE ? LIMIT 50',('%'+q+'%',)*3)])
# Функция player: см. параметры, описание и вызовы ниже.
@router.get('/players/{uid}')
def player(uid:int,user=Depends(moderator_user)):
    from fishing import ensure_fishing,snapshot
    with session(write=True) as db:
        if not db.execute('SELECT 1 FROM players WHERE telegram_id=?',(uid,)).fetchone():raise HTTPException(404,'Нет игрока')
        ensure_fishing(db,uid);return snapshot(db,uid)
# Класс Block: см. параметры, описание и вызовы ниже.
class Block(BaseModel):
    blocked:bool=True
    reason:str=Field(default='',max_length=300)
# Функция block: см. параметры, описание и вызовы ниже.
@router.post('/players/{uid}/block')
def block(uid:int,data:Block,user=Depends(moderator_user)):
    if uid==ADMIN_ID:raise HTTPException(403,'Нельзя заблокировать администратора')
    with session(write=True) as db:
        if not db.execute('SELECT 1 FROM players WHERE telegram_id=?',(uid,)).fetchone():raise HTTPException(404,'Нет игрока')
        db.execute('UPDATE bh SET blocked=?,reason=? WHERE telegram_id=?',(int(data.blocked),data.reason,uid));db.execute('INSERT INTO admin_log(ts,admin_id,target,action,value) VALUES (?,?,?,?,?)',(int(time.time()),user['id'],uid,'block',data.model_dump_json()))
    return dict(ok=True)
# Функция top: см. параметры, описание и вызовы ниже.
@router.get('/top')
def top(kind:str='level',user=Depends(current_user)):
    from fishing import FISH_BY_ID,TIERS,level_info
    if kind not in ('level','coins','record'):raise HTTPException(400,'Нет рейтинга')
    with session() as db:
        if kind=='record':
            records={}
            for r in db.execute('SELECT h.*,p.nickname,p.telegram_name,pr.prefix FROM fishing_catch_history h JOIN players p USING(telegram_id) JOIN bh b USING(telegram_id) LEFT JOIN profiles_v11 pr USING(telegram_id) WHERE b.blocked=0'):
                f=FISH_BY_ID.get(r['fish_key'])
                if f and (r['telegram_id'] not in records or (TIERS.index(f['rarity']),r['kg'])>records[r['telegram_id']]['score']):records[r['telegram_id']]={**dict(r),'fish_name':f['name'],'rarity':f['rarity'],'score':(TIERS.index(f['rarity']),r['kg'])}
            rows=sorted(records.values(),key=lambda r:r['score'],reverse=True)[:10]
        else:
            order='COALESCE(f.xp,0)' if kind=='level' else 'p.coins'
            rows=[{**dict(r),'level':level_info(r['xp'])['level']} for r in db.execute(f'SELECT p.telegram_id,p.nickname,p.telegram_name,p.coins,COALESCE(f.xp,0) xp,pr.prefix FROM players p JOIN bh b USING(telegram_id) LEFT JOIN fishing_progress f USING(telegram_id) LEFT JOIN profiles_v11 pr USING(telegram_id) WHERE b.blocked=0 ORDER BY {order} DESC,p.telegram_id LIMIT 10')]
    return dict(players=rows)


# Функция list_promos: см. параметры, описание и вызовы ниже.
@router.get('/admin/promos')
def list_promos(admin=Depends(admin_user)):
    with session() as db:
        rows=db.execute('SELECT p.*, (SELECT COUNT(*) FROM promo_claims_v11 c WHERE c.code=p.code) AS claimed FROM promos_v11 p ORDER BY rowid DESC LIMIT 200').fetchall()
    return {'promos':[dict(r) for r in rows]}

# Функция list_moderators: см. параметры, описание и вызовы ниже.
@router.get('/admin/moderators')
def list_moderators(admin=Depends(admin_user)):
    with session() as db:
        rows=db.execute('SELECT p.telegram_id,p.nickname,p.telegram_name,p.coins,b.avatar,b.last_seen,b.blocked,pr.prefix FROM profiles_v11 pr JOIN players p USING(telegram_id) JOIN bh b USING(telegram_id) WHERE pr.moderator=1 ORDER BY p.telegram_id').fetchall()
    return {'players':[dict(r) for r in rows]}

# Класс ReleaseFish: см. параметры, описание и вызовы ниже.
class ReleaseFish(BaseModel):
    id:int=Field(gt=0)

# Функция release_fish: см. параметры, описание и вызовы ниже.
@router.post('/fish/release')
def release_fish(data:ReleaseFish,user=Depends(current_user)):
    """Give a modest amount of experience for releasing a caught fish."""
    from fishing import snapshot,ensure_fishing
    uid=user['id']
    with session(write=True) as db:
        ensure_fishing(db,uid)
        caught=next((f for f in catch_rows(db,uid,'bag') if f['id']==data.id),None)
        if not caught:raise HTTPException(404,'Рыба не найдена в подсаке')
        # Intentionally smaller than earnings from selling or catching.
        xp=min(12,max(2,2+int(caught['value']**0.25)))
        db.execute('DELETE FROM catches_v11 WHERE id=? AND telegram_id=? AND place=?',(data.id,uid,'bag'))
        db.execute('UPDATE fishing_fish SET amount=MAX(0,amount-1) WHERE telegram_id=? AND item_key=?',(uid,caught['key']))
        db.execute('UPDATE fishing_progress SET xp=xp+? WHERE telegram_id=?',(xp,uid))
        return dict(xp=xp,state=snapshot(db,uid))
