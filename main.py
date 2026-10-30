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
app = FastAPI(title='Monster Islands', version='1.0.0')
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
    return [dict(instance_id=r['id'],obtained=r['obtained'],**CATALOG[r['monster_id']]) for r in rows]

@app.get('/')
def home():return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/health')
def health():return {'status':'ok','version':'1.0.0'}

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

BUILDINGS = {'tree': 0, 'garden': 120, 'lantern': 60}
with sqlite3.connect(DB_FILE) as _con:
    _con.execute('CREATE TABLE IF NOT EXISTS island_state (owner_id INTEGER PRIMARY KEY, x REAL NOT NULL DEFAULT 0.5, y REAL NOT NULL DEFAULT 0.58)')
    _con.execute('CREATE TABLE IF NOT EXISTS island_buildings (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL, kind TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL)')

@app.get('/api/island')
def get_island(x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        state=con.execute('SELECT x,y FROM island_state WHERE owner_id=?',(uid,)).fetchone()
        structures=con.execute('SELECT id,kind,x,y FROM island_buildings WHERE owner_id=?',(uid,)).fetchall()
        return {'position':dict(state) if state else {'x':0.5,'y':0.58}, 'buildings':[dict(r) for r in structures]}

@app.put('/api/island/position')
def save_position(payload:IslandState,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    with transaction() as con:
        ensure_player(con,uid,name)
        con.execute('INSERT INTO island_state(owner_id,x,y) VALUES (?,?,?) ON CONFLICT(owner_id) DO UPDATE SET x=excluded.x,y=excluded.y',(uid,payload.x,payload.y))
    return {'saved':True}

@app.post('/api/island/build')
def place_building(payload:NewBuilding,x_telegram_init_data: str|None=Header(default=None)):
    uid,name=identity(x_telegram_init_data)
    if payload.kind not in BUILDINGS: raise HTTPException(400,'Неизвестная постройка')
    with transaction() as con:
        player=ensure_player(con,uid,name)
        count=con.execute('SELECT COUNT(*) FROM island_buildings WHERE owner_id=?',(uid,)).fetchone()[0]
        if count>=25:raise HTTPException(400,'Достигнут лимит построек')
        cost=BUILDINGS[payload.kind]
        if player['coins']<cost:raise HTTPException(400,'Недостаточно монет')
        nearby=con.execute('SELECT 1 FROM island_buildings WHERE owner_id=? AND (x-?)*(x-?)+(y-?)*(y-?)<0.0064 LIMIT 1',(uid,payload.x,payload.x,payload.y,payload.y)).fetchone()
        if nearby:raise HTTPException(400,'Слишком близко к другой постройке')
        con.execute('UPDATE players SET coins=coins-? WHERE telegram_id=?',(cost,uid))
        cur=con.execute('INSERT INTO island_buildings(owner_id,kind,x,y) VALUES (?,?,?,?)',(uid,payload.kind,payload.x,payload.y))
        updated=con.execute('SELECT * FROM players WHERE telegram_id=?',(uid,)).fetchone()
        return {'building':{'id':cur.lastrowid,'kind':payload.kind,'x':payload.x,'y':payload.y},'player':player_data(updated)}
