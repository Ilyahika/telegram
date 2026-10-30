"""Monster Islands backend; Telegram initData must be signed on the server."""
import hashlib
import hmac
import json
import os
import random
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DB_FILE = Path(os.getenv('DB_PATH', str(ROOT / 'monster_islands.sqlite3')))
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
DEV_DEMO = os.getenv('DEV_DEMO', '0') == '1'
app = FastAPI(title='Monster Islands', version='2.0.0')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

MONSTERS = [
('leafy','Листик','common','nature','#6ecb79',3),('drop','Капелька','common','water','#5dc7ed',3),('rocky','Камушек','common','earth','#9facbd',3),('spark','Искрик','common','fire','#ffa35a',3),('moss','Моховик','common','nature','#84be61',4),('sand','Песчаник','common','earth','#e7bf79',3),
('aqua','Аквариус','rare','water','#4ca8e8',8),('ember','Огневик','rare','fire','#ff806d',8),('bolt','Громик','rare','storm','#f4cd60',8),('frost','Ледолис','rare','ice','#a4e1fa',8),('shade','Тенёк','rare','shadow','#8f88d3',7),
('lunar','Лунарис','epic','moon','#a489f5',15),('crystal','Кристаликс','epic','crystal','#60d9cc',15),('flora','Флоракс','epic','nature','#87de9c',15),('storm','Штормон','epic','storm','#7da8fc',15),
('pyro','Пиродракон','legendary','fire','#ff975a',25),('ocean','Океанор','legendary','water','#4dc3ff',25),('terra','Террагард','legendary','earth','#deb17d',25),('phoenix','Фениксар','mythic','fire','#ff6587',35),('astral','Астралион','exclusive','cosmic','#d9b8ff',20)
]
RARITY_RU={'common':'Обычный','rare':'Редкий','epic':'Эпический','legendary':'Легендарный','mythic':'Мифический','exclusive':'Эксклюзивный'}
CATALOG={m[0]:dict(id=m[0],name=m[1],rarity=m[2],rarity_name=RARITY_RU[m[2]],element=m[3],color=m[4],bonus=m[5],icon=f'/static/monsters/{m[0]}-icon.svg',portrait=f'/static/monsters/{m[0]}-portrait.svg') for m in MONSTERS}
CASES=[{'id':'forest','name':'Лесной кейс','price':120,'colors':['#4e9860','#a1ea91'],'chances':{'common':75,'rare':22,'epic':3}}, {'id':'magic','name':'Магический кейс','price':400,'colors':['#5c83e2','#88d8fa'],'chances':{'common':35,'rare':45,'epic':18,'legendary':2}}, {'id':'ancient','name':'Древний кейс','price':1200,'colors':['#8154cf','#eb9fff'],'chances':{'rare':35,'epic':45,'legendary':18,'mythic':2}}, {'id':'star','name':'Звёздный кейс','price':3000,'colors':['#eb994f','#ffe097'],'chances':{'epic':50,'legendary':37,'mythic':12,'exclusive':1}}]
CASE_BY_ID={c['id']:c for c in CASES}

def init_database():
    DB_FILE.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB_FILE, timeout=15) as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('CREATE TABLE IF NOT EXISTS players (telegram_id INTEGER PRIMARY KEY, name TEXT NOT NULL, coins INTEGER NOT NULL DEFAULT 1200, crystals INTEGER NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 1, created INTEGER NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS owned_monsters (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL, monster_id TEXT NOT NULL, obtained INTEGER NOT NULL, FOREIGN KEY(owner_id) REFERENCES players(telegram_id))')
        con.execute('CREATE INDEX IF NOT EXISTS monsters_by_owner ON owned_monsters(owner_id)')
        con.execute('CREATE TABLE IF NOT EXISTS case_openings (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL, case_id TEXT NOT NULL, owned_id INTEGER NOT NULL, created INTEGER NOT NULL)')

init_database()

@contextmanager
def transaction():
    connection=sqlite3.connect(DB_FILE,timeout=15,isolation_level=None)
    connection.row_factory=sqlite3.Row
    try:
        connection.execute('BEGIN IMMEDIATE')
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def verify_init_data(data: str):
    if not BOT_TOKEN:
        raise HTTPException(503,'BOT_TOKEN не настроен')
    if not data or len(data)>16000:
        raise HTTPException(401,'Отсутствуют данные Telegram')
    try:
        pairs=dict(parse_qsl(data,keep_blank_values=True,strict_parsing=True))
        provided=pairs.pop('hash','')
        auth_date=int(pairs['auth_date'])
        if not (0 <= time.time()-auth_date <= 86400):
            raise ValueError('initData устарел')
        check='\n'.join(f'{key}={value}' for key,value in sorted(pairs.items()))
        secret=hmac.new(b'WebAppData',BOT_TOKEN.encode(),hashlib.sha256).digest()
        expected=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided,expected):
            raise ValueError('Неверная подпись')
        user=json.loads(pairs['user'])
        user_id=int(user['id'])
        if user_id<=0:
            raise ValueError('Некорректный id')
        return user_id, str(user.get('first_name') or user.get('username') or 'Игрок')[:64]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(401,f'Авторизация Telegram не пройдена: {exc}') from exc

def identity(x_telegram_init_data: str|None):
    if DEV_DEMO and not x_telegram_init_data:
        return -1001,'Тестовый игрок'
    return verify_init_data(x_telegram_init_data or '')

def ensure_player(con,player_id,name):
    con.execute('INSERT OR IGNORE INTO players(telegram_id,name,created) VALUES (?,?,?)',(player_id,name,int(time.time())))
    con.execute('UPDATE players SET name=? WHERE telegram_id=?',(name,player_id))
    return con.execute('SELECT * FROM players WHERE telegram_id=?',(player_id,)).fetchone()

def player_data(row):
    return {'id':row['telegram_id'],'nickname':row['name'],'coins':row['coins'],'crystals':row['crystals'],'level':row['level']}

def inventory(con,player_id):
    rows=con.execute('SELECT id, monster_id, obtained FROM owned_monsters WHERE owner_id=? ORDER BY id DESC',(player_id,)).fetchall()
    return [dict(instance_id=r['id'],obtained=r['obtained'],listed=bool(con.execute("SELECT 1 FROM market WHERE owned_id=? AND status='active'",(r['id'],)).fetchone()),**CATALOG[r['monster_id']]) for r in rows]

@app.get('/')
def home():return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/health')
def health():return {'status':'ok','version':'2.0.0'}

@app.post('/api/auth')
def auth(x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        player=ensure_player(con,uid,name)
        owned=inventory(con,uid)
        return {'player':player_data(player),'inventory':owned,'demo':uid<0}

@app.get('/api/catalog')
def catalog():return {'monsters':list(CATALOG.values()),'cases':CASES}

@app.get('/api/inventory')
def get_inventory(x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        return {'inventory':inventory(con,uid)}

class OpenCase(BaseModel):
    case_id: str = Field(min_length=1,max_length=30)

@app.post('/api/cases/open')
def open_case(payload:OpenCase,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    case=CASE_BY_ID.get(payload.case_id)
    if not case:raise HTTPException(404,'Кейс не найден')
    with transaction() as con:
        player=ensure_player(con,uid,name)
        if not con.execute("SELECT 1 FROM island_buildings WHERE owner_id=? AND kind='shop'",(uid,)).fetchone():
            raise HTTPException(403,'Сначала построй магазин в обучении')
        if player['coins']<case['price']:
            raise HTTPException(400,'Недостаточно монет')
        con.execute('UPDATE players SET coins=coins-? WHERE telegram_id=?',(case['price'],uid))
        chances=case['chances']; rarity=random.choices(list(chances),weights=list(chances.values()),k=1)[0]
        candidates=[m for m in CATALOG.values() if m['rarity']==rarity]
        chosen=random.SystemRandom().choice(candidates)
        now=int(time.time())
        cursor=con.execute('INSERT INTO owned_monsters(owner_id,monster_id,obtained) VALUES (?,?,?)',(uid,chosen['id'],now))
        con.execute('INSERT INTO case_openings(owner_id,case_id,owned_id,created) VALUES (?,?,?,?)',(uid,case['id'],cursor.lastrowid,now))
        updated=con.execute('SELECT * FROM players WHERE telegram_id=?',(uid,)).fetchone()
        return {'reward':dict(instance_id=cursor.lastrowid,obtained=now,**chosen),'player':player_data(updated)}

# Island progress is stored server-side per authenticated Telegram player.
class IslandState(BaseModel):
    x: float = Field(ge=0.03, le=0.97)
    y: float = Field(ge=0.03, le=0.97)

class NewBuilding(BaseModel):
    kind: str
    x: float = Field(ge=0.05, le=0.95)
    y: float = Field(ge=0.05, le=0.95)

BUILDINGS = {'shop': 0, 'expedition': 450, 'friends': 300}
TOWNHALL = {'id':0, 'kind':'townhall','x':0.50,'y':0.48}
with sqlite3.connect(DB_FILE) as _con:
    _con.execute('CREATE TABLE IF NOT EXISTS island_state (owner_id INTEGER PRIMARY KEY, x REAL NOT NULL DEFAULT 0.50, y REAL NOT NULL DEFAULT 0.57)')
    _con.execute('CREATE TABLE IF NOT EXISTS island_buildings (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL, kind TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL)')
    _con.execute('CREATE TABLE IF NOT EXISTS progress (owner_id INTEGER PRIMARY KEY, tutorial INTEGER NOT NULL DEFAULT 0, last_claim INTEGER NOT NULL DEFAULT 0, last_expedition INTEGER NOT NULL DEFAULT 0)')

def ensure_progress(con,uid):
    con.execute('INSERT OR IGNORE INTO progress(owner_id) VALUES(?)',(uid,))
    return con.execute('SELECT * FROM progress WHERE owner_id=?',(uid,)).fetchone()

def active_buildings(con,uid):
    structures=con.execute('SELECT id,kind,x,y FROM island_buildings WHERE owner_id=?',(uid,)).fetchall()
    return [TOWNHALL,*[dict(r) for r in structures]]

@app.get('/api/island')
def get_island(x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        progress=ensure_progress(con,uid)
        state=con.execute('SELECT x,y FROM island_state WHERE owner_id=?',(uid,)).fetchone()
        return {'position':dict(state) if state else {'x':0.5,'y':0.57},'buildings':active_buildings(con,uid), 'tutorial':progress['tutorial'], 'townhall':TOWNHALL,'server_time':int(time.time()), 'last_claim':progress['last_claim'], 'last_expedition':progress['last_expedition']}

@app.put('/api/island/position')
def save_position(payload:IslandState,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        con.execute('INSERT INTO island_state(owner_id,x,y) VALUES (?,?,?) ON CONFLICT(owner_id) DO UPDATE SET x=excluded.x,y=excluded.y',(uid,payload.x,payload.y))
    return {'saved':True}

class TutorialStep(BaseModel):
    step: int = Field(ge=1,le=3)

@app.post('/api/tutorial/advance')
def advance_tutorial(payload:TutorialStep,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        p=ensure_progress(con,uid)
        current=p['tutorial']
        if payload.step==current:return {'tutorial':current}
        if payload.step!=current+1:raise HTTPException(409,'Проходи обучение по порядку')
        if payload.step==3 and not con.execute("SELECT 1 FROM island_buildings WHERE owner_id=? AND kind='shop'",(uid,)).fetchone():
            raise HTTPException(409,'Сначала построй магазин')
        con.execute('UPDATE progress SET tutorial=? WHERE owner_id=?',(payload.step,uid))
        return {'tutorial':payload.step}

@app.post('/api/island/build')
def place_building(payload:NewBuilding,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    if payload.kind not in BUILDINGS:raise HTTPException(400,'Неизвестная постройка')
    with transaction() as con:
        player=ensure_player(con,uid,name)
        progress=ensure_progress(con,uid)
        if progress['tutorial']<2:raise HTTPException(403,'Сначала пройди обучение управлению')
        if progress['tutorial']<3 and payload.kind!='shop':raise HTTPException(403,'Сначала построй магазин')
        if con.execute('SELECT 1 FROM island_buildings WHERE owner_id=? AND kind=?',(uid,payload.kind)).fetchone():raise HTTPException(409,'Это здание уже построено')
        cost=BUILDINGS[payload.kind]
        if player['coins']<cost:raise HTTPException(400,'Недостаточно монет')
        x,y=payload.x*96,payload.y*72
        if x<31 or x>64 or y<21 or y>52:raise HTTPException(400,'Строить можно только на центральной территории')
        if ((x-48)**2+(y-34.56)**2)<25:raise HTTPException(400,'Нельзя строить вплотную к ратуше')
        rows=con.execute('SELECT x,y FROM island_buildings WHERE owner_id=?',(uid,)).fetchall()
        if any(((r['x']-payload.x)*96)**2+((r['y']-payload.y)*72)**2<35 for r in rows):raise HTTPException(400,'Рядом уже есть здание')
        con.execute('UPDATE players SET coins=coins-? WHERE telegram_id=?',(cost,uid))
        cur=con.execute('INSERT INTO island_buildings(owner_id,kind,x,y) VALUES(?,?,?,?)',(uid,payload.kind,payload.x,payload.y))
        return {'building':{'id':cur.lastrowid,'kind':payload.kind,'x':payload.x,'y':payload.y},'player':player_data(con.execute('SELECT * FROM players WHERE telegram_id=?',(uid,)).fetchone())}

@app.post('/api/townhall/claim')
def claim_income(x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name);p=ensure_progress(con,uid)
        now=int(time.time());elapsed=now-p['last_claim'] if p['last_claim'] else 3600
        reward=min(720,max(0,elapsed//60)*2)
        if reward<2:raise HTTPException(429,'Доход пока не накопился')
        con.execute('UPDATE progress SET last_claim=? WHERE owner_id=?',(now,uid))
        con.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(reward,uid))
        return {'earned':reward,'last_claim':now,'player':player_data(con.execute('SELECT * FROM players WHERE telegram_id=?',(uid,)).fetchone())}

@app.post('/api/expedition/collect')
def expedition_collect(x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        if not con.execute("SELECT 1 FROM island_buildings WHERE owner_id=? AND kind='expedition'",(uid,)).fetchone():raise HTTPException(403,'Построй экспедицию')
        p=ensure_progress(con,uid);now=int(time.time())
        if now-p['last_expedition']<3600:raise HTTPException(429,'Следующая экспедиция через '+str(3600-(now-p['last_expedition']))+' сек')
        reward=250
        con.execute('UPDATE progress SET last_expedition=? WHERE owner_id=?',(now,uid))
        con.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(reward,uid))
        return {'earned':reward,'player':player_data(con.execute('SELECT * FROM players WHERE telegram_id=?',(uid,)).fetchone())}

# Trading market: every operation is atomic, ownership and funds are checked server-side.
with sqlite3.connect(DB_FILE) as _con:
    _con.execute("CREATE TABLE IF NOT EXISTS market (id INTEGER PRIMARY KEY AUTOINCREMENT, seller INTEGER NOT NULL, owned_id INTEGER NOT NULL UNIQUE, price INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active', buyer INTEGER, created INTEGER NOT NULL)")
    _con.execute("CREATE INDEX IF NOT EXISTS market_active ON market(status,created)")
    _con.execute("CREATE TABLE IF NOT EXISTS selected_companions (owner_id INTEGER PRIMARY KEY, monster_owned_id INTEGER NOT NULL)")

class MarketOffer(BaseModel):
    owned_id: int = Field(gt=0)
    price: int = Field(ge=10,le=1000000)

@app.get('/api/market')
def market_list():
    with sqlite3.connect(DB_FILE) as con:
        con.row_factory=sqlite3.Row
        rows=con.execute("SELECT m.id,m.seller,m.price,m.created,o.monster_id FROM market m JOIN owned_monsters o ON o.id=m.owned_id WHERE m.status='active' ORDER BY m.created DESC LIMIT 100").fetchall()
        return {'listings':[dict(listing_id=r['id'],seller_id=r['seller'],price=r['price'],created=r['created'],**CATALOG[r['monster_id']]) for r in rows]}

@app.post('/api/market/list')
def market_create(payload:MarketOffer,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        owned=con.execute('SELECT id FROM owned_monsters WHERE id=? AND owner_id=?',(payload.owned_id,uid)).fetchone()
        if not owned:raise HTTPException(403,'Монстр тебе не принадлежит')
        listed=con.execute("SELECT id FROM market WHERE owned_id=? AND status='active'",(payload.owned_id,)).fetchone()
        if listed:raise HTTPException(409,'Этот монстр уже продаётся')
        cur=con.execute("INSERT INTO market(seller,owned_id,price,status,created) VALUES (?,?,?,'active',?)",(uid,payload.owned_id,payload.price,int(time.time())))
        return {'listing_id':cur.lastrowid}

@app.post('/api/market/{listing_id}/buy')
def market_buy(listing_id:int,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        player=ensure_player(con,uid,name)
        offer=con.execute("SELECT * FROM market WHERE id=? AND status='active'",(listing_id,)).fetchone()
        if not offer:raise HTTPException(404,'Объявление неактивно')
        if offer['seller']==uid:raise HTTPException(400,'Нельзя купить своего монстра')
        if player['coins']<offer['price']:raise HTTPException(400,'Недостаточно монет')
        valid=con.execute('SELECT id FROM owned_monsters WHERE id=? AND owner_id=?',(offer['owned_id'],offer['seller'])).fetchone()
        if not valid:raise HTTPException(409,'Монстр больше недоступен')
        fee=(offer['price']*5+99)//100
        con.execute('UPDATE players SET coins=coins-? WHERE telegram_id=?',(offer['price'],uid))
        con.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(offer['price']-fee,offer['seller']))
        con.execute('UPDATE owned_monsters SET owner_id=? WHERE id=?',(uid,offer['owned_id']))
        con.execute("UPDATE market SET status='sold',buyer=? WHERE id=?",(uid,listing_id))
        con.execute('DELETE FROM selected_companions WHERE owner_id=? AND monster_owned_id=?',(offer['seller'],offer['owned_id']))
        return {'ok':True,'player':player_data(con.execute('SELECT * FROM players WHERE telegram_id=?',(uid,)).fetchone())}

@app.post('/api/market/{listing_id}/cancel')
def market_cancel(listing_id:int,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        changed=con.execute("UPDATE market SET status='cancelled' WHERE id=? AND seller=? AND status='active'",(listing_id,uid)).rowcount
        if not changed:raise HTTPException(404,'Нет доступного объявления')
        return {'ok':True}

class CompanionChoice(BaseModel):
    owned_id: int = Field(gt=0)

@app.get('/api/companion')
def companion_get(x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        row=con.execute('SELECT monster_owned_id FROM selected_companions WHERE owner_id=?',(uid,)).fetchone()
        return {'owned_id':row['monster_owned_id'] if row else None}

@app.post('/api/companion')
def companion_set(choice:CompanionChoice,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        valid=con.execute("SELECT o.id FROM owned_monsters o WHERE o.id=? AND o.owner_id=? AND NOT EXISTS(SELECT 1 FROM market m WHERE m.owned_id=o.id AND m.status='active')",(choice.owned_id,uid)).fetchone()
        if not valid:raise HTTPException(403,'Выбрать этого монстра нельзя')
        con.execute('INSERT INTO selected_companions(owner_id,monster_owned_id) VALUES(?,?) ON CONFLICT(owner_id) DO UPDATE SET monster_owned_id=excluded.monster_owned_id',(uid,choice.owned_id))
        return {'ok':True}
