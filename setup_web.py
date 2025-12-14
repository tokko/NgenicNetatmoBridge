import os
import json
import httpx
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from rich.console import Console

console = Console()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Temporary storage (in-memory, single user)
setup_data = {
    "netatmo_client_id": "",
    "netatmo_client_secret": "",
    "netatmo_temp_token": "",
    "netatmo_refresh_token": "",
    "ngenic_refresh_token": "",
    "netatmo_rooms": [],
    "ngenic_rooms": [],
    "mapping": {}
}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/step/netatmo-app", response_class=HTMLResponse)
async def step_netatmo_app(request: Request):
    return templates.TemplateResponse("netatmo_app.html", {"request": request})

@app.post("/step/netatmo-app")
async def save_netatmo_app(
    client_id: str = Form(...),
    client_secret: str = Form(...)
):
    setup_data["netatmo_client_id"] = client_id.strip()
    setup_data["netatmo_client_secret"] = client_secret.strip()
    return RedirectResponse("/step/netatmo-token", status_code=302)

@app.get("/step/netatmo-token", response_class=HTMLResponse)
async def step_netatmo_token(request: Request):
    return templates.TemplateResponse("netatmo_token.html", {"request": request})

@app.post("/step/netatmo-token")
async def validate_netatmo_token(temp_token: str = Form(...)):
    token = temp_token.strip()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.netatmo.com/api/homesdata",
            headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code != 200:
            raise HTTPException(400, f"Invalid token: {resp.status_code}")
        homes = resp.json()["body"]["homes"]
        rooms = []
        for home in homes:
            for room in home.get("rooms", []):
                rooms.append({
                    "home_id": home["id"],
                    "home_name": home.get("name", "Home"),
                    "room_id": room["id"],
                    "room_name": room.get("name", "Room")
                })
        setup_data["netatmo_rooms"] = rooms
        setup_data["netatmo_temp_token"] = token
    return RedirectResponse("/step/ngenic", status_code=302)

@app.get("/step/ngenic", response_class=HTMLResponse)
async def step_ngenic(request: Request):
    return templates.TemplateResponse("ngenic.html", {"request": request})

@app.post("/step/ngenic")
async def validate_ngenic(refresh_token: str = Form(...)):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.ngenic.com/auth/token",
            json={
                "grantType": "refresh_token",
                "clientId": "tune_web",
                "clientSecret": "c98ead25-07d7-4a47-9bcd-7d5c6a5f20d7",
                "refreshToken": refresh_token.strip()
            }
        )
        if resp.status_code != 200:
            raise HTTPException(400, "Invalid Ngenic refresh token")
        access_token = resp.json()["accessToken"]

        tunes_resp = await client.get("https://api.ngenic.com/v3/tune/tunes", headers={"Authorization": f"Bearer {access_token}"})
        tunes = tunes_resp.json()
        rooms = []
        for tune in tunes:
            rooms_resp = await client.get(f"https://api.ngenic.com/v3/tune/tunes/{tune['uuid']}/rooms",
                                          headers={"Authorization": f"Bearer {access_token}"})
            for room in rooms_resp.json():
                rooms.append({
                    "uuid": room["uuid"],
                    "name": room.get("name", "Unnamed")
                })
        setup_data["ngenic_rooms"] = rooms
        setup_data["ngenic_refresh_token"] = refresh_token.strip()
    return RedirectResponse("/step/mapping", status_code=302)

@app.get("/step/mapping", response_class=HTMLResponse)
async def step_mapping(request: Request):
    if not setup_data["netatmo_rooms"] or not setup_data["ngenic_rooms"]:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("mapping.html", {
        "request": request,
        "ngenic_rooms": setup_data["ngenic_rooms"],
        "netatmo_rooms": setup_data["netatmo_rooms"]
    })

@app.post("/step/mapping")
async def save_mapping(request: Request):
    form = await request.form()
    mapping = []
    for key in form.keys():
        if key.startswith("ngenic_"):
            uuid = key.split("_")[1]
            netatmo_idx = int(form[key])
            netatmo_room = setup_data["netatmo_rooms"][netatmo_idx]
            mapping.append({
                "ngenic_room_uuid": uuid,
                "netatmo_home_id": netatmo_room["home_id"],
                "netatmo_room_id": netatmo_room["room_id"]
            })
    setup_data["mapping"] = mapping
    return RedirectResponse("/step/final", status_code=302)

@app.get("/step/final", response_class=HTMLResponse)
async def step_final(request: Request):
    return templates.TemplateResponse("final.html", {"request": request})

@app.post("/complete")
async def complete_setup(netatmo_refresh_token: str = Form(...)):
    setup_data["netatmo_refresh_token"] = netatmo_refresh_token.strip()

    config = {
        "netatmo": {
            "client_id": setup_data["netatmo_client_id"],
            "client_secret": setup_data["netatmo_client_secret"],
            "refresh_token": setup_data["netatmo_refresh_token"]
        },
        "ngenic": {
            "client_id": "tune_web",
            "client_secret": "c98ead25-07d7-4a47-9bcd-7d5c6a5f20d7",
            "refresh_token": setup_data["ngenic_refresh_token"]
        },
        "mapping": setup_data["mapping"]
    }

    host_path = "/host"
    with open(f"{host_path}/config.json", "w") as f:
        json.dump(config, f, indent=2)

    os.makedirs(f"{host_path}/docker-secrets", exist_ok=True)
    secrets = {
        "netatmo_client_id": setup_data["netatmo_client_id"],
        "netatmo_client_secret": setup_data["netatmo_client_secret"],
        "netatmo_refresh_token": setup_data["netatmo_refresh_token"],
        "ngenic_refresh_token": setup_data["ngenic_refresh_token"]
    }
    for name, value in secrets.items():
        with open(f"{host_path}/docker-secrets/{name}", "w") as f:
            f.write(value + "\n")

    return templates.TemplateResponse("complete.html", {"request": None})
