"""Viva Beta V1: secure shop, referrals, pass, partnerships and admin controls."""
import json, re, secrets, sqlite3, time, tempfile, os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from auth import current_user, admin_user
from db import session
from config import ADMIN_ID, DB_PATH

router=APIRouter(prefix='/api/v14')
LEVELS=30

# Функция migrate: см. параметры, описание и вызовы ниже.
def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS viva_wallet(uid INTEGER PRIMARY KEY, stars INTEGER NOT NULL DEFAULT 0 CHECK(stars>=0), vivip INTEGER NOT NULL DEFAULT 0, pass_claim INTEGER NOT NULL DEFAULT 0, vip_claim INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS viva_payments(charge_id TEXT PRIMARY KEY, uid INTEGER NOT NULL, stars INTEGER NOT NULL, created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS viva_referrals(invited INTEGER PRIMARY KEY, inviter INTEGER NOT NULL, created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS viva_partner(uid INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', requested INTEGER NOT NULL, approved INTEGER NOT NULL DEFAULT 0, last_promo INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS viva_partner_promos(code TEXT PRIMARY KEY, uid INTEGER NOT NULL, coins INTEGER NOT NULL, cases TEXT NOT NULL, uses INTEGER NOT NULL, expires INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS viva_partner_claims(code TEXT NOT NULL,uid INTEGER NOT NULL, PRIMARY KEY(code,uid));
    CREATE TABLE IF NOT EXISTS viva_config(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS viva_section_maintenance(section TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0);
    ''')
    for key,val in {'ref_inviter':'1000','ref_invited':'500','starter_stars':'50','starter_coins':'10000','starter_xp':'250','starter_gear':'starter_rod','starter_enabled':'1'}.items():
        db.execute('INSERT OR IGNORE INTO viva_config VALUES (?,?)',(key,val))

# Функция config: см. параметры, описание и вызовы ниже.
def config(db,key):return db.execute('SELECT value FROM viva_config WHERE key=?',(key,)).fetchone()[0]
# Функция wallet: см. параметры, описание и вызовы ниже.
def wallet(db,uid):
    db.execute('INSERT OR IGNORE INTO viva_wallet(uid) VALUES (?)',(uid,))
    return db.execute('SELECT * FROM viva_wallet WHERE uid=?',(uid,)).fetchone()
# Функция add_case: см. параметры, описание и вызовы ниже.
def add_case(db,uid,key,amount=1):
    db.execute('INSERT INTO fishing_cases(telegram_id,case_key,amount) VALUES(?,?,?) ON CONFLICT(telegram_id,case_key) DO UPDATE SET amount=amount+excluded.amount',(uid,key,amount))
# Функция put_notice: см. параметры, описание и вызовы ниже.
def put_notice(db,uid,message):
    db.execute('INSERT INTO notices_v11(telegram_id,kind,text) VALUES (?,?,?)',(uid,'gift',message))
# Функция grant: см. параметры, описание и вызовы ниже.
def grant(db,uid,coins=0,xp=0,cases=None,gear=None):
    db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(int(coins),uid))
    db.execute('UPDATE fishing_progress SET xp=xp+? WHERE telegram_id=?',(int(xp),uid))
    for case in (cases or []):add_case(db,uid,case)
    if gear:db.execute('INSERT INTO fishing_gear(telegram_id,gear_key,amount) VALUES(?,?,1) ON CONFLICT(telegram_id,gear_key) DO UPDATE SET amount=amount+1',(uid,gear))

# Функция pass_reward: см. параметры, описание и вызовы ниже.
def pass_reward(level,vip):
    return dict(coins=level*(900 if vip else 300),cases=['rod_0' if not vip else 'rod_1'] if level%5==0 else [],clover=2 if vip and level%10==0 else 0)

# Функция state: см. параметры, описание и вызовы ниже.
@router.get('/state')
def state(user=Depends(current_user)):
    from fishing import level_info
    uid=user['id']
    with session(write=True) as db:
        w=wallet(db,uid); xp=db.execute('SELECT xp FROM fishing_progress WHERE telegram_id=?',(uid,)).fetchone()
        ref=db.execute('SELECT COUNT(*) FROM viva_referrals WHERE inviter=?',(uid,)).fetchone()[0]
        partner=db.execute('SELECT * FROM viva_partner WHERE uid=?',(uid,)).fetchone()
        invited=[dict(x) for x in db.execute("SELECT r.invited AS id,r.created AS created,COALESCE(p.nickname,p.telegram_name,'Игрок') AS name FROM viva_referrals r LEFT JOIN players p ON p.telegram_id=r.invited WHERE r.inviter=? ORDER BY r.created DESC LIMIT 100",(uid,)).fetchall()]
        return dict(stars=w['stars'],vivip=bool(w['vivip']),pass_claim=w['pass_claim'],vip_claim=w['vip_claim'],pass_level=min(30,level_info(xp[0] if xp else 0)['level']),referrals=ref,invited_players=invited,pass_rewards=[{'level':i, 'free':pass_reward(i,False), 'premium':pass_reward(i,True)} for i in range(1,31)],sections={x['section']:bool(x['enabled']) for x in db.execute('SELECT * FROM viva_section_maintenance')},ref_inviter=int(config(db,'ref_inviter')),ref_invited=int(config(db,'ref_invited')),starter=dict(price=int(config(db,'starter_stars')),coins=int(config(db,'starter_coins')),xp=int(config(db,'starter_xp')),enabled=config(db,'starter_enabled')=='1'),partner=dict(partner) if partner else None)

# Класс Invite: см. параметры, описание и вызовы ниже.
class Invite(BaseModel):inviter:int
# Функция referral: см. параметры, описание и вызовы ниже.
@router.post('/referral')
def referral(data:Invite,user=Depends(current_user)):
    uid=user['id'];now=int(time.time())
    with session(write=True) as db:
        if data.inviter<=0 or uid==data.inviter:raise HTTPException(400,'Недопустимая ссылка')
        if not db.execute('SELECT 1 FROM players WHERE telegram_id=?',(data.inviter,)).fetchone():raise HTTPException(404,'Пригласивший игрок не найден')
        if db.execute('SELECT 1 FROM viva_referrals WHERE invited=?',(uid,)).fetchone():raise HTTPException(409,'Награда за приглашение уже получена')
        # Only accounts created very recently can claim a referral, to prevent re-linking old accounts.
        created=db.execute('SELECT created_at FROM players WHERE telegram_id=?',(uid,)).fetchone()[0]
        if now-created>900:raise HTTPException(409,'Реферальная награда только для новых игроков')
        db.execute('INSERT INTO viva_referrals VALUES(?,?,?)',(uid,data.inviter,now))
        a=int(config(db,'ref_inviter'));b=int(config(db,'ref_invited'))
        db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(a,data.inviter))
        db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(b,uid))
    return {'ok':True,'reward':b}

# Класс Buy: см. параметры, описание и вызовы ниже.
class Buy(BaseModel):product:str
# Функция buy: см. параметры, описание и вызовы ниже.
@router.post('/buy')
def buy(data:Buy,user=Depends(current_user)):
    from fishing import ensure_fishing
    uid=user['id']
    with session(write=True) as db:
        ensure_fishing(db,uid);w=wallet(db,uid)
        if data.product not in ('starter','vivip'):raise HTTPException(400,'Неизвестный товар')
        price=int(config(db,'starter_stars')) if data.product=='starter' else 250
        if data.product=='starter' and config(db,'starter_enabled')!='1':raise HTTPException(409,'Товар недоступен')
        if data.product=='vivip' and w['vivip']:raise HTTPException(409,'ViVip уже активен')
        if w['stars']<price:raise HTTPException(409,'Недостаточно звёзд Viva')
        db.execute('UPDATE viva_wallet SET stars=stars-? WHERE uid=?',(price,uid))
        if data.product=='vivip':db.execute('UPDATE viva_wallet SET vivip=1 WHERE uid=?',(uid,))
        else:
            from fishing import GEAR_BY_ID
            gear=config(db,'starter_gear');gear=gear if gear in GEAR_BY_ID else None
            grant(db,uid,int(config(db,'starter_coins')),int(config(db,'starter_xp')),gear=gear)
    return {'ok':True}

# Класс Claim: см. параметры, описание и вызовы ниже.
class Claim(BaseModel):track:str;level:int=Field(ge=1,le=30)
# Функция claim: см. параметры, описание и вызовы ниже.
@router.post('/pass/claim')
def claim(data:Claim,user=Depends(current_user)):
    from fishing import level_info
    uid=user['id'];vip=data.track=='vivip'
    if data.track not in ('viva','vivip'):raise HTTPException(400,'Неверный пропуск')
    with session(write=True) as db:
        w=wallet(db,uid)
        if vip and not w['vivip']:raise HTTPException(409,'Нужен ViVip')
        xp=db.execute('SELECT xp FROM fishing_progress WHERE telegram_id=?',(uid,)).fetchone()[0]
        if level_info(xp)['level']<data.level:raise HTTPException(409,'Уровень ещё не достигнут')
        field='vip_claim' if vip else 'pass_claim'
        if w[field]+1!=data.level:raise HTTPException(409,'Сначала забери предыдущие награды')
        reward=pass_reward(data.level,vip)
        grant(db,uid,reward['coins'],cases=reward['cases'])
        if reward['clover']:
            db.execute('INSERT INTO fishing_buffs(telegram_id,multiplier,expires_at) VALUES(?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET multiplier=MAX(multiplier,excluded.multiplier),expires_at=MAX(expires_at,excluded.expires_at)',(uid,2,time.time()+reward['clover']*3600))
        db.execute(f'UPDATE viva_wallet SET {field}=? WHERE uid=?',(data.level,uid))
    return dict(ok=True,reward=reward)

# Класс PartnerRequest: см. параметры, описание и вызовы ниже.
class PartnerRequest(BaseModel):chat_id:int;description:str=Field(min_length=3,max_length=240)
# Функция apply: см. параметры, описание и вызовы ниже.
@router.post('/partner/apply')
async def apply(data:PartnerRequest,user=Depends(current_user)):
    from botapp import state as bot_state
    from aiogram.enums import ChatMemberStatus
    bot=bot_state.bot
    if not bot:raise HTTPException(503,'Бот недоступен')
    try:
        me=await bot.get_me();member=await bot.get_chat_member(data.chat_id,me.id)
        if member.status not in (ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.CREATOR):raise ValueError('not admin')
    except Exception:raise HTTPException(409,'Добавь бота администратором канала или группы')
    with session(write=True) as db:
        db.execute('INSERT INTO viva_partner(uid,chat_id,description,status,requested) VALUES(?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET chat_id=excluded.chat_id,description=excluded.description,status="pending",requested=excluded.requested',(user['id'],data.chat_id,data.description,'pending',int(time.time())))
    return {'ok':True}

# Класс PartnerPromo: см. параметры, описание и вызовы ниже.
class PartnerPromo(BaseModel):code:str=Field(min_length=3,max_length=24);coins:int=Field(ge=0,le=1000000);cases:list[str]=Field(default_factory=list,max_length=3);uses:int=Field(ge=1,le=100)
# Функция partner_promo: см. параметры, описание и вызовы ниже.
@router.post('/partner/promo')
def partner_promo(data:PartnerPromo,user=Depends(current_user)):
    from fishing import CASES
    uid=user['id'];code=data.code.strip().upper();now=int(time.time())
    if not re.fullmatch('[A-Z0-9_-]{3,24}',code):raise HTTPException(400,'Недопустимый код')
    allowed={c['key'] for c in CASES}
    if any(c not in allowed for c in data.cases):raise HTTPException(400,'Неизвестный кейс')
    with session(write=True) as db:
        p=db.execute('SELECT * FROM viva_partner WHERE uid=?',(uid,)).fetchone()
        if not p or p['status']!='approved':raise HTTPException(403,'Нет подтверждённого статуса партнёра')
        if now-p['last_promo']<10800:raise HTTPException(429,'Один промокод в 3 часа')
        if db.execute('SELECT 1 FROM promos_v11 WHERE code=? UNION SELECT 1 FROM viva_partner_promos WHERE code=?',(code,code)).fetchone():raise HTTPException(409,'Код занят')
        # A partner can only distribute assets they already own, reserved upfront.
        total=data.coins*data.uses
        bal=db.execute('SELECT coins FROM players WHERE telegram_id=?',(uid,)).fetchone()[0]
        if bal<total:raise HTTPException(409,'Не хватает денег на все активации')
        for key in set(data.cases):
            count=data.cases.count(key)*data.uses
            have=db.execute('SELECT amount FROM fishing_cases WHERE telegram_id=? AND case_key=?',(uid,key)).fetchone()
            if not have or have[0]<count:raise HTTPException(409,f'Недостаточно кейсов {key}')
        db.execute('UPDATE players SET coins=coins-? WHERE telegram_id=?',(total,uid))
        for key in set(data.cases):db.execute('UPDATE fishing_cases SET amount=amount-? WHERE telegram_id=? AND case_key=?',(data.cases.count(key)*data.uses,uid,key))
        db.execute('INSERT INTO viva_partner_promos VALUES(?,?,?,?,?,?)',(code,uid,data.coins,json.dumps(data.cases),data.uses,now+1800))
        db.execute('UPDATE viva_partner SET last_promo=? WHERE uid=?',(now,uid))
    return {'ok':True,'expires':now+1800}

# Класс Promo: см. параметры, описание и вызовы ниже.
class Promo(BaseModel):code:str
# Функция redeem: см. параметры, описание и вызовы ниже.
@router.post('/partner/redeem')
def redeem(data:Promo,user=Depends(current_user)):
    code=data.code.strip().upper();uid=user['id']
    with session(write=True) as db:
        r=db.execute('SELECT * FROM viva_partner_promos WHERE code=?',(code,)).fetchone()
        if not r or r['expires']<time.time() or r['uses']<=0:raise HTTPException(409,'Промокод недоступен')
        if r['uid']==uid:raise HTTPException(409,'Нельзя активировать свой промокод')
        if db.execute('SELECT 1 FROM viva_partner_claims WHERE code=? AND uid=?',(code,uid)).fetchone():raise HTTPException(409,'Уже активирован')
        db.execute('INSERT INTO viva_partner_claims VALUES (?,?)',(code,uid));db.execute('UPDATE viva_partner_promos SET uses=uses-1 WHERE code=?',(code,))
        grant(db,uid,r['coins'],cases=json.loads(r['cases']))
    return {'ok':True}

# Функция settings: см. параметры, описание и вызовы ниже.
@router.get('/admin/settings')
def settings(admin=Depends(admin_user)):
    with session() as db:return dict(settings={r['key']:r['value'] for r in db.execute('SELECT * FROM viva_config')},partners=[dict(x) for x in db.execute('SELECT * FROM viva_partner ORDER BY requested DESC LIMIT 100')],sections=[dict(x) for x in db.execute('SELECT * FROM viva_section_maintenance')])
# Класс Setting: см. параметры, описание и вызовы ниже.
class Setting(BaseModel):key:str;value:str
# Функция set_setting: см. параметры, описание и вызовы ниже.
@router.post('/admin/settings')
def set_setting(data:Setting,admin=Depends(admin_user)):
    keys={'ref_inviter','ref_invited','starter_stars','starter_coins','starter_xp','starter_gear','starter_enabled'}
    if data.key not in keys:raise HTTPException(400,'Нельзя менять этот параметр')
    if data.key=='starter_gear':
        from fishing import GEAR_BY_ID
        if data.value not in GEAR_BY_ID:raise HTTPException(400,'Нет такой экипировки')
    elif not data.value.isdigit() or int(data.value)>1000000000:raise HTTPException(400,'Нужно положительное целое число')
    with session(write=True) as db:db.execute('UPDATE viva_config SET value=? WHERE key=?',(data.value,data.key))
    return {'ok':True}
# Класс Approval: см. параметры, описание и вызовы ниже.
class Approval(BaseModel):uid:int;approved:bool
# Функция approval: см. параметры, описание и вызовы ниже.
@router.post('/admin/partner')
def approval(data:Approval,admin=Depends(admin_user)):
    with session(write=True) as db:
        result=db.execute('UPDATE viva_partner SET status=?,approved=? WHERE uid=?',('approved' if data.approved else 'rejected',int(time.time()),data.uid))
        if not result.rowcount:raise HTTPException(404,'Заявка не найдена')
    return {'ok':True}
# Класс Section: см. параметры, описание и вызовы ниже.
class Section(BaseModel):section:str;enabled:bool
# Функция maintenance: см. параметры, описание и вызовы ниже.
@router.post('/admin/section')
def maintenance(data:Section,admin=Depends(admin_user)):
    if data.section not in ('fish','bag','shop','donate','pass','referral','chat','rewards','top','profile','partner'):raise HTTPException(400,'Неизвестная вкладка')
    with session(write=True) as db:db.execute('INSERT INTO viva_section_maintenance VALUES (?,?) ON CONFLICT(section) DO UPDATE SET enabled=excluded.enabled',(data.section,int(data.enabled)))
    return {'ok':True}

# Credits are granted exclusively after Telegram's authenticated successful_payment update.
def credit_payment(uid:int,stars:int,charge_id:str):
    if not (1<=stars<=10000) or not charge_id:return False
    with session(write=True) as db:
        wallet(db,uid)
        res=db.execute('INSERT OR IGNORE INTO viva_payments VALUES(?,?,?,?)',(charge_id,uid,stars,int(time.time())))
        if not res.rowcount:return False
        db.execute('UPDATE viva_wallet SET stars=stars+? WHERE uid=?',(stars,uid))
    return True

# Функция invoice: см. параметры, описание и вызовы ниже.
@router.post('/invoice/{amount}')
async def invoice(amount:int,user=Depends(current_user)):
    from botapp import state
    if amount not in (50,100,250,500):raise HTTPException(400,'Недоступный пакет')
    if not state.bot:raise HTTPException(503,'Бот недоступен')
    payload=f'viva_{amount}_{user["id"]}_{secrets.token_hex(8)}'
    try:
        link=await state.bot.create_invoice_link(title=f'Viva Shop · {amount} ⭐',description='Внутриигровая валюта Viva',payload=payload,currency='XTR',prices=[{'label':f'{amount} звёзд Viva','amount':amount}])
    except Exception:raise HTTPException(503,'Не удалось создать счёт в Telegram')
    return {'url':link}

# Функция backup_to_admin_chat: см. параметры, описание и вызовы ниже.
@router.post('/admin/backup')
async def backup_to_admin_chat(admin=Depends(admin_user)):
    """Snapshot active SQLite and deliver privately to the configured admin via Telegram."""
    from aiogram.types import BufferedInputFile
    from botapp import state as bot_state
    if not bot_state.bot:
        raise HTTPException(503, 'Бот не подключён. Проверь BOT_TOKEN и запусти бота.')
    with tempfile.NamedTemporaryFile(suffix='.db') as f:
        source=sqlite3.connect(str(DB_PATH)); dest=sqlite3.connect(f.name)
        try:
            source.backup(dest)
        finally:
            dest.close(); source.close()
        payload=Path(f.name).read_bytes()
    try:
        await bot_state.bot.send_document(
            chat_id=ADMIN_ID,
            document=BufferedInputFile(payload, filename='viva-backup.db'),
            caption='💾 Актуальная резервная копия базы Viva. Храни файл в безопасном месте.'
        )
    except Exception as exc:
        import logging
        logging.getLogger('viva.backup').exception('Failed to send DB backup to admin')
        raise HTTPException(502, 'Не получилось отправить базу. Открой личный чат с ботом, нажми /start и попробуй снова.') from exc
    return {'ok': True, 'message': '✅ База отправлена в личный чат администратора с ботом.'}

# Функция stage_backup: см. параметры, описание и вызовы ниже.
@router.post('/admin/backup/stage')
async def stage_backup(request: Request,admin=Depends(admin_user)):
    """Only stage verified replacement DB; never hot-swap a live SQLite database."""
    from fastapi import Request
    content=await request.body()
    if len(content)>100*1024*1024 or not content.startswith(b'SQLite format 3\x00'):
        raise HTTPException(400,'Файл не является SQLite или превышает 100 МБ')
    staged=DB_PATH.with_suffix('.restore-pending.db')
    with tempfile.NamedTemporaryFile(dir=DB_PATH.parent,delete=False) as f:
        f.write(content);temp=f.name
    try:
        c=sqlite3.connect(f'file:{temp}?mode=ro',uri=True)
        try:
            valid=c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:c.close()
        if not valid or not {'players','bh','fishing_progress','fishing_gear'}<=tables:
            raise HTTPException(400,'База повреждена или несовместима')
        os.replace(temp,staged)
    finally:Path(temp).unlink(missing_ok=True)
    return {'ok':True,'message':'База проверена и подготовлена. Для безопасного восстановления останови сервер, сохрани текущую БД и замени её staged-файлом, затем перезапусти сервер.'}
