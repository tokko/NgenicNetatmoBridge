import httpx
import json
import getpass
import os
import sys
from rich.prompt import Prompt, IntPrompt
from rich.console import Console
from rich.panel import Panel

console = Console()

def create_netatmo_app():
    console.print(Panel("[bold blue]Netatmo Developer App[/bold blue]", expand=False))
    console.print("Go to: [link=https://dev.netatmo.com/apps/]https://dev.netatmo.com/apps/[/]")
    console.print("Click 'Create an app' → fill name/description → copy Client ID and Secret\n")
    client_id = Prompt.ask("[bold]Netatmo Client ID[/bold]")
    client_secret = Prompt.ask("[bold]Netatmo Client Secret[/bold]", password=True)
    return client_id.strip(), client_secret.strip()

def get_netatmo_token(client_id, client_secret):
    console.print(Panel("[bold blue]Netatmo Account Login[/bold blue]", expand=False))
    username = Prompt.ask("Netatmo email")
    password = getpass.getpass("Netatmo password (hidden): ")

    with httpx.Client(timeout=30.0) as client:
        try:
            resp = client.post(
                "https://api.netatmo.com/oauth2/token",
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": username,
                    "password": password,
                    "scope": "read_thermostat write_thermostat"
                }
            )
            resp.raise_for_status()
        except Exception as e:
            console.print(f"[red]Netatmo login failed: {e}[/red]")
            sys.exit(1)

    console.print("[green]✓ Netatmo authentication successful![/green]")
    return resp.json()["access_token"], username, password

def fetch_netatmo_homes(access_token):
    console.print("\n[bold]Fetching your Netatmo homes and rooms...[/bold]")
    with httpx.Client() as client:
        resp = client.post(
            "https://api.netatmo.com/api/homesdata",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        resp.raise_for_status()
        homes = resp.json()["body"]["homes"]

    netatmo_rooms = []
    for home in homes:
        home_id = home["id"]
        home_name = home.get("name", "Unnamed home")
        console.print(f"\n[bold cyan]Home:[/bold cyan] {home_name} (id: {home_id})")
        for room in home.get("rooms", []):
            room_id = room["id"]
            room_name = room.get("name", "Unnamed room")
            console.print(f"   • {room_name} → id: {room_id}")
            netatmo_rooms.append({
                "home_id": home_id,
                "home_name": home_name,
                "room_id": room_id,
                "room_name": room_name
            })
    return netatmo_rooms

def get_ngenic_refresh_token():
    console.print(Panel("[bold magenta]Ngenic Tune Refresh Token[/bold magenta]", expand=False))
    console.print("1. Open [link=https://tune.ngenic.com]https://tune.ngenic.com[/] and log in")
    console.print("2. Press F12 → Network tab → Refresh page")
    console.print("3. Find request to '/auth/token' → copy the long 'refreshToken' from payload\n")
    refresh_token = Prompt.ask("Paste refresh_token here", password=True)
    return refresh_token.strip()

def get_ngenic_access_token(refresh_token):
    with httpx.Client() as client:
        resp = client.post(
            "https://api.ngenic.com/auth/token",
            json={
                "grantType": "refresh_token",
                "clientId": "tune_web",
                "clientSecret": "c98ead25-07d7-4a47-9bcd-7d5c6a5f20d7",
                "refreshToken": refresh_token
            }
        )
        resp.raise_for_status()
    console.print("[green]✓ Ngenic token valid![/green]")
    return resp.json()["accessToken"]

def fetch_ngenic_rooms(access_token):
    console.print("\n[bold]Fetching Ngenic Tune rooms...[/bold]")
    with httpx.Client() as client:
        tunes_resp = client.get("https://api.ngenic.com/v3/tune/tunes", headers={"Authorization": f"Bearer {access_token}"})
        tunes_resp.raise_for_status()
        tunes = tunes_resp.json()

        ngenic_rooms = []
        for tune in tunes:
            tune_name = tune.get("name", "My House")
            console.print(f"\n[bold cyan]Tune:[/bold cyan] {tune_name}")
            rooms_resp = client.get(f"https://api.ngenic.com/v3/tune/tunes/{tune['uuid']}/rooms",
                                    headers={"Authorization": f"Bearer {access_token}"})
            rooms_resp.raise_for_status()
            for room in rooms_resp.json():
                name = room.get("name", "Unnamed")
                uuid = room["uuid"]
                temp = room.get("currentTemperature")
                console.print(f"   • {name} → uuid: {uuid} (current: {temp}°C)")
                ngenic_rooms.append({"room_uuid": uuid, "room_name": name})
    return ngenic_rooms

def map_rooms(ngenic_rooms, netatmo_rooms):
    console.print(Panel("[bold yellow]Room Mapping[/bold yellow]", expand=False))
    mapping = []
    for ng_room in ngenic_rooms:
        console.print(f"\n[bold]Ngenic →[/bold] {ng_room['room_name']} (uuid: {ng_room['room_uuid']})")
        console.print("Choose corresponding Netatmo room:")
        for i, nt in enumerate(netatmo_rooms):
            console.print(f"  [{i+1}] {nt['room_name']} ({nt['home_name']})")
        console.print("  [skip] or [s] to skip this room")

        choice = Prompt.ask("Your choice", choices=[str(i+1) for i in range(len(netatmo_rooms))] + ["skip", "s"], default="skip")
        if choice in ["skip", "s"]:
            continue
        idx = int(choice) - 1
        selected = netatmo_rooms[idx]
        mapping.append({
            "ngenic_room_uuid": ng_room["room_uuid"],
            "netatmo_home_id": selected["home_id"],
            "netatmo_room_id": selected["room_id"]
        })
        console.print(f"[green]→ Mapped to[/green] {selected['room_name']}")
    return mapping

def main():
    console.print(Panel("[bold green]Netatmo ← Ngenic Bridge Setup Wizard[/bold green]", expand=False))

    client_id, client_secret = create_netatmo_app()
    netatmo_token, username, password = get_netatmo_token(client_id, client_secret)
    netatmo_rooms = fetch_netatmo_homes(netatmo_token)

    refresh_token = get_ngenic_refresh_token()
    ngenic_token = get_ngenic_access_token(refresh_token)
    ngenic_rooms = fetch_ngenic_rooms(ngenic_token)

    mapping = map_rooms(ngenic_rooms, netatmo_rooms)
    if not mapping:
        console.print("[red]No rooms mapped → exiting.[/red]")
        sys.exit(1)

    # Write config.json
    config = {
        "netatmo": {
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password
        },
        "ngenic": {
            "client_id": "tune_web",
            "client_secret": "c98ead25-07d7-4a47-9bcd-7d5c6a5f20d7",
            "refresh_token": refresh_token
        },
        "mapping": mapping
    }

    with open("/host/config.json", "w") as f:
        json.dump(config, f, indent=2)
    console.print("\n[green]✓ config.json written to host![/green]")

    # Create secret files on host
    os.makedirs("/host/docker-secrets", exist_ok=True)
    secrets = {
        "netatmo_client_id": client_id,
        "netatmo_client_secret": client_secret,
        "netatmo_username": username,
        "netatmo_password": password,
        "ngenic_refresh_token": refresh_token
    }
    for name, value in secrets.items():
        path = f"/host/docker-secrets/{name}"
        with open(path, "w") as f:
            f.write(value + "\n")
    console.print("[green]✓ All Docker secret files created in ./docker-secrets/[/green]")

    console.print(Panel("[bold green]Setup complete![/bold green]\nNow run: [bold cyan]docker compose up -d --build[/bold cyan]", expand=False))

if __name__ == "__main__":
    main()
