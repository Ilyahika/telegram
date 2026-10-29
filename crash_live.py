"""Общий аркадный Crash: один серверный таймер и состояние для всех клиентов.

Никаких ставок, пополнений, вывода денег или призов. Результаты — очки
для визуального соревнования и не влияют на баланс игрока.
"""
import asyncio
import math
import random
import time
from contextlib import suppress

from fastapi import WebSocket

WAIT_SECONDS = 20  # Время между раундами после окончания
TICK_SECONDS = 0.1  # Как часто рассылается состояние игрокам

class CrashRoom:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.round_id = 0
        self.phase = 'waiting'
        self.ends_at = time.time() + 5
        self.multiplier = 1.0
        self.crash_at = 1.0
        self.started_at = 0.0
        self.history: list[float] = []
        self.task = None

    def snapshot(self):
        return {'type': 'state', 'round': self.round_id, 'phase': self.phase,
                'server_time': time.time(), 'ends_at': self.ends_at,
                'multiplier': round(self.multiplier, 2),
                'history': self.history[-12:]}

    async def broadcast(self):
        state = self.snapshot()
        for client in tuple(self.clients):
            try:
                await client.send_json(state)
            except Exception:
                self.clients.discard(client)

    async def run(self):
        """Один фоновый цикл на один экземпляр процесса FastAPI."""
        while True:
            try:
                # Начальный либо межраундовый отсчёт.
                self.phase = 'waiting'
                while time.time() < self.ends_at:
                    await self.broadcast()
                    await asyncio.sleep(TICK_SECONDS)

                self.round_id += 1
                self.phase = 'running'
                self.multiplier = 1.0
                self.started_at = time.monotonic()
                # Независимый случайный предел анимации, не денежный выигрыш.
                self.crash_at = round(min(20.0, 1 + random.expovariate(0.42)), 2)
                while self.multiplier < self.crash_at:
                    elapsed = time.monotonic() - self.started_at
                    self.multiplier = min(self.crash_at, math.exp(elapsed * 0.23))
                    await self.broadcast()
                    await asyncio.sleep(TICK_SECONDS)

                self.phase = 'finished'
                self.history.append(self.crash_at)
                self.history = self.history[-12:]
                self.ends_at = time.time() + WAIT_SECONDS
                await self.broadcast()
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Восстанавливаем цикл, даже если клиент отключился во время рассылки.
                self.ends_at = time.time() + WAIT_SECONDS
                await asyncio.sleep(1)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.clients.add(websocket)
        await websocket.send_json(self.snapshot())
        try:
            while True:
                # Сообщения от клиента не могут влиять на результат раунда.
                await websocket.receive_text()
        finally:
            self.clients.discard(websocket)

room = CrashRoom()
