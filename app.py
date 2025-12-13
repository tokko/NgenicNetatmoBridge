from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import json
import asyncio
import logging
from typing import Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("netatmo-ngenic-bridge")

app = FastAPI(title="Netatmo ← Ngenic Auto-Sync Bridge", version="2.0")

with open("config.json") as f:
    config = json.load(f)

NETATMO = config["netatmo"]
NGENIC = config["ngenic"]
MAPPING = config["mapping"]

# Token cache
netatmo_token: str = None
ngenic_token: str = None
token_lock = asyncio.Lock()

# Remember last known target from Ngenic to avoid unnecessary calls
last_known_targets: Dict[str, float] = {room["ngenic_room_uuid"]: None for room in MAPPING}

async def get_netatmo_token() -> str:
    global netatmo_token
    async with token_lock:
        if netatmo_token:
            return netatmo_token
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.netatmo.com/api/getaccesstoken",
                data={
                    "grant_type": "password",
                    "client_id": NETATMO["client_id"],
                    "client_secret": NETATMO["client_secret"],
                    "username": NETATMO["username"],
                    "password": NETATMO["password"],
                    "scope": "read_thermostat write_thermostat"
                }
            )
            r.raise_for_status()
            netatmo_token = r.json()["access_token"]
            logger.info("Netatmo token refreshed")
            return netatmo_token

async def get_ngenic_token() -> str:
    global ngenic_token
    async with token_lock:
        if ngenic_token:
            return ngenic_token
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.ngenic.com/auth/token",
                json={
                    "grantType": "refresh_token",
                    "clientId": NGENIC["client_id"],
                    "clientSecret": NGENIC["client_secret"],
                    "refreshToken": NGENIC["refresh_token"]
                }
            )
            r.raise_for_status()
            ngenic_token = r.json()["accessToken"]
            logger.info("Ngenic token refreshed")
            return ngenic_token

async def sync_once():
    try:
        ngenic_token = await get_ngenic_token()
        netatmo_token = await get_netatmo_token()

        async with httpx.AsyncClient() as client:
            for room in MAPPING:
                uuid = room["ngenic_room_uuid"]
                r = await client.get(
                    f"https://api.ngenic.com/v3/tune/rooms/{uuid}",
                    headers={"Authorization": f"Bearer {ngenic_token}"}
                )
                r.raise_for_status()
                data = r.json()

                current_temp = data["currentTemperature"]
                override = data.get("targetTemperature")
                target_temp = override.get("temperature") if override else None

                # Decide what to send to Netatmo
                desired_temp = target_temp
                desired_mode = "manual" if override else "program"

                # Only act if something changed (or first run)
                if last_known_targets[uuid] == desired_temp and desired_mode == "program":
                    continue  # no change

                last_known_targets[uuid] = desired_temp

                payload = {
                    "home": {
                        "id": room["netatmo_home_id"],
                        "rooms": [{
                            "id": room["netatmo_room_id"],
                            "therm_setpoint_temperature": round(desired_temp, 1) if desired_temp else 19,
                            "therm_setpoint_mode": desired_mode
                        }]
                    }
                }

                # If manual override on Ngenic → extend Netatmo override far into future
                if override:
                    # Ngenic override usually lasts 1–24 h → we set Netatmo to 8 hours ahead (safe)
                    import time
                    payload["home"]["rooms"][0]["therm_setpoint_end_time"] = int(time.time()) + 8*3600

                r_net = await client.post(
                    "https://api.netatmo.com/api/setthermpoint",
                    headers={"Authorization": f"Bearer {netatmo_token}"},
                    data=payload
                )

                if r_net.status_code == 200:
                    logger.info(f"SYNC → Room {uuid[-8:]}: {current_temp}°C → Netatmo {'schedule' if not override else desired_temp}°C")
                else:
                    logger.error(f"Netatmo failed: {r_net.text}")

    except Exception as e:
        logger.error(f"Sync failed: {e}")

async def background_sync():
    await asyncio.sleep(10)  # initial delay
    while True:
        await sync_once()
        await asyncio.sleep(300)  # 5 minutes

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_sync())
    logger.info("Auto-sync background task started – will sync every 5 min")

# === REST API (still available for manual control or debugging) ===

@app.get("/status")
async def status():
    token = await get_ngenic_token()
    results = []
    async with httpx.AsyncClient() as client:
        for room in MAPPING:
            r = await client.get(
                f"https://api.ngenic.com/v3/tune/rooms/{room['ngenic_room_uuid']}",
                headers={"Authorization": f"Bearer {token}"}
            )
            data = r.json() if r.status_code == 200 else {}
            results.append({
                "ngenic_room_uuid": room["ngenic_room_uuid"],
                "current_temp": data.get("currentTemperature"),
                "ngenic_target": data.get("targetTemperature", {}).get("temperature") if data.get("targetTemperature") else None,
                "last_synced_target": last_known_targets[room["ngenic_room_uuid"]]
            })
    return results

class ManualSet(BaseModel):
    temperature: float
    hours: int = 4

@app.post("/manual-set")
async def manual_set(req: ManualSet):
    token = await get_netatmo_token()
    async with httpx.AsyncClient() as client:
        for room in MAPPING:
            payload = {
                "home": {
                    "id": room["netatmo_home_id"],
                    "rooms": [{
                        "id": room["netatmo_room_id"],
                        "therm_setpoint_temperature": req.temperature,
                        "therm_setpoint_mode": "manual",
                        "therm_setpoint_end_time": int(__import__('time').time()) + req.hours * 3600
                    }]
                }
            }
            await client.post("https://api.netatmo.com/api/setthermpoint",
                              headers={"Authorization": f"Bearer {token}"}, data=payload)
    return {"status": "manual override set", "temp": req.temperature, "hours": req.hours}

@app.post("/follow-schedule")
async def follow_schedule():
    token = await get_netatmo_token()
    async with httpx.AsyncClient() as client:
        for room in MAPPING:
            await client.post(
                "https://api.netatmo.com/api/setthermpoint",
                headers={"Authorization": f"Bearer {token}"},
                data={"home": {"id": room["netatmo_home_id"], "rooms": [{"id": room["netatmo_room_id"], "therm_setpoint_mode": "program"}]}}
            )
    return {"status": "all rooms back to Netatmo schedule"}
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import json
import asyncio
import logging
import os
from typing import Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("netatmo-ngenic-bridge")

app = FastAPI(title="Netatmo ← Ngenic Auto-Sync Bridge", version="2.0")

# Helper to read from Docker secrets or env vars
def read_secret(name: str) -> str:
    secret_path = f"/run/secrets/{name}"
    if os.path.exists(secret_path):
        with open(secret_path) as f:
            return f.read().strip()
    # Fallback to environment variable
    env_name = name.upper().replace("-", "_")
    value = os.getenv(env_name)
    if not value:
        raise ValueError(f"Missing secret or env var: {name} / {env_name}")
    return value

# Load credentials from secrets / env
NETATMO_CLIENT_ID = read_secret("netatmo_client_id")
NETATMO_CLIENT_SECRET = read_secret("netatmo_client_secret")
NETATMO_USERNAME = read_secret("netatmo_username")
NETATMO_PASSWORD = read_secret("netatmo_password")
NGENIC_REFRESH_TOKEN = read_secret("ngenic_refresh_token")

# Load mapping from config.json (static, generated by setup.py)
with open("config.json") as f:
    MAPPING = json.load(f)["mapping"]

if not MAPPING:
    raise ValueError("No room mapping found in config.json")

# Token cache
netatmo_token: str = None
ngenic_token: str = None
token_lock = asyncio.Lock()

# Last known targets to avoid unnecessary updates
last_known_targets: Dict[str, float | None] = {room["ngenic_room_uuid"]: None for room in MAPPING}
last_known_mode: Dict[str, str] = {room["ngenic_room_uuid"]: "program" for room in MAPPING}

async def get_netatmo_token() -> str:
    global netatmo_token
    async with token_lock:
        if netatmo_token:
            return netatmo_token
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.netatmo.com/oauth2/token",
                data={
                    "grant_type": "password",
                    "client_id": NETATMO_CLIENT_ID,
                    "client_secret": NETATMO_CLIENT_SECRET,
                    "username": NETATMO_USERNAME,
                    "password": NETATMO_PASSWORD,
                    "scope": "read_thermostat write_thermostat"
                }
            )
            r.raise_for_status()
            netatmo_token = r.json()["access_token"]
            logger.info("Netatmo token refreshed")
            return netatmo_token

async def get_ngenic_token() -> str:
    global ngenic_token
    async with token_lock:
        if ngenic_token:
            return ngenic_token
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.ngenic.com/auth/token",
                json={
                    "grantType": "refresh_token",
                    "clientId": "tune_web",
                    "clientSecret": "c98ead25-07d7-4a47-9bcd-7d5c6a5f20d7",
                    "refreshToken": NGENIC_REFRESH_TOKEN
                }
            )
            r.raise_for_status()
            ngenic_token = r.json()["accessToken"]
            logger.info("Ngenic token refreshed")
            return ngenic_token

async def sync_once():
    try:
        ngenic_token = await get_ngenic_token()
        netatmo_token = await get_netatmo_token()

        async with httpx.AsyncClient() as client:
            for room in MAPPING:
                uuid = room["ngenic_room_uuid"]
                r = await client.get(
                    f"https://api.ngenic.com/v3/tune/rooms/{uuid}",
                    headers={"Authorization": f"Bearer {ngenic_token}"}
                )
                r.raise_for_status()
                data = r.json()

                current_temp = data["currentTemperature"]
                override = data.get("targetTemperature")
                target_temp = override.get("temperature") if override else None
                desired_mode = "manual" if override else "program"
                desired_temp = round(target_temp, 1) if target_temp else None

                # Only update if changed
                if last_known_targets[uuid] == desired_temp and last_known_mode[uuid] == desired_mode:
                    continue

                last_known_targets[uuid] = desired_temp
                last_known_mode[uuid] = desired_mode

                payload = {
                    "home": {
                        "id": room["netatmo_home_id"],
                        "rooms": [{
                            "id": room["netatmo_room_id"],
                            "therm_setpoint_mode": desired_mode
                        }]
                    }
                }

                if desired_mode == "manual" and desired_temp:
                    payload["home"]["rooms"][0]["therm_setpoint_temperature"] = desired_temp
                    # Extend far into future to keep override active
                    import time
                    payload["home"]["rooms"][0]["therm_setpoint_end_time"] = int(time.time()) + 24 * 3600

                r_net = await client.post(
                    "https://api.netatmo.com/api/setthermpoint",
                    headers={"Authorization": f"Bearer {netatmo_token}"},
                    data=payload
                )

                if r_net.status_code == 200:
                    logger.info(f"SYNC → Room {uuid[-6:]}: {current_temp}°C → Netatmo {'schedule' if desired_mode == 'program' else desired_temp}°C")
                else:
                    logger.error(f"Netatmo sync failed: {r_net.text}")

    except Exception as e:
        logger.error(f"Sync error: {e}")

async def background_sync():
    await asyncio.sleep(15)  # Wait a bit on startup
    while True:
        await sync_once()
        await asyncio.sleep(300)  # Every 5 minutes

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_sync())
    logger.info("Auto-sync started – checking every 5 minutes")

# REST API
@app.get("/status")
async def status():
    token = await get_ngenic_token()
    results = []
    async with httpx.AsyncClient() as client:
        for room in MAPPING:
            r = await client.get(
                f"https://api.ngenic.com/v3/tune/rooms/{room['ngenic_room_uuid']}",
                headers={"Authorization": f"Bearer {token}"}
            )
            data = r.json() if r.status_code == 200 else {}
            results.append({
                "ngenic_room_uuid": room["ngenic_room_uuid"],
                "current_temp": data.get("currentTemperature"),
                "ngenic_target": data.get("targetTemperature", {}).get("temperature") if data.get("targetTemperature") else "schedule",
                "last_synced_to_netatmo": last_known_targets[room["ngenic_room_uuid"]]
            })
    return results

class ManualSet(BaseModel):
    temperature: float
    hours: int = 4

@app.post("/manual-set")
async def manual_set(req: ManualSet):
    token = await get_netatmo_token()
    import time
    async with httpx.AsyncClient() as client:
        for room in MAPPING:
            payload = {
                "home": {
                    "id": room["netatmo_home_id"],
                    "rooms": [{
                        "id": room["netatmo_room_id"],
                        "therm_setpoint_temperature": req.temperature,
                        "therm_setpoint_mode": "manual",
                        "therm_setpoint_end_time": int(time.time()) + req.hours * 3600
                    }]
                }
            }
            await client.post(
                "https://api.netatmo.com/api/setthermpoint",
                headers={"Authorization": f"Bearer {token}"},
                data=payload
            )
    return {"status": "manual override applied", "temp": req.temperature, "hours": req.hours}

@app.post("/follow-schedule")
async def follow_schedule():
    token = await get_netatmo_token()
    async with httpx.AsyncClient() as client:
        for room in MAPPING:
            payload = {
                "home": {
                    "id": room["netatmo_home_id"],
                    "rooms": [{"id": room["netatmo_room_id"], "therm_setpoint_mode": "program"}]
                }
            }
            await client.post(
                "https://api.netatmo.com/api/setthermpoint",
                headers={"Authorization": f"Bearer {token}"},
                data=payload
            )
    return {"status": "all rooms set to follow Netatmo schedule"}
