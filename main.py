from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
players = {}

@app.get("/")
def home():
    return {'message': "Добро пожаловать!"}

class PlayerCreate(BaseModel):
    name: str



@app.get("/player")
def get_player(player: PlayerCreate):
    player_id = max(player.keys(), default=0) + 1
    players[player_id] = {
        "name": 'Player',
        "coins": 100
    }
    return {
        "id": player_id,
        "player": players[player_id]
    }