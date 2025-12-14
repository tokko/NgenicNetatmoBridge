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
    console.print("Log in with your Netatmo account → Create a new app (any name/description)\n")
    client_id = Prompt.ask("[bold]Netatmo Client ID[/bold]")
    client_secret = Prompt.ask("[bold]Netatmo Client Secret[/bold]", password=True)
    return client_id.strip(), client_secret.strip()

def get_netatmo_access_token_for_setup(client_id, client_secret):
    console.print(Panel("[bold blue]Generate Initial Netatmo Access Token[/bold blue]", expand=False))
    console.print("1. Go to https://dev.netatmo.com/apps/")
    console.print("2. Select your app")
    console.print("3. Scroll down to 'Token generator' section")
    console.print("4. Select scopes: [bold]read_thermostat[/bold] and [bold]write_thermostat[/bold]")
    console.print("5. Click 'Generate token'")
    console.print("6. Copy the [bold]access_token[/bold] (it lasts 3 hours – we only need it briefly)\n")
    access_token = Prompt.ask("Paste the temporary access_token here", password=True)
    return access_token.strip()

def fetch_netatmo_homes(access_token):
    console.print("\n[bold]Fetching your Netatmo homes and rooms...[/bold]")
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            "https://api.netatmo.com/api/homesdata",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if resp.status_code != 200:
            console.print(f"[red]Failed to fetch homes: {resp.status_code} {resp.text}[/red]")
            sys.exit(1)
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
    if not netatmo_rooms:
        console.print("[red]No thermostat rooms found. Make sure your app has thermostat scopes.[/red]")
        sys.exit(1)
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
        if resp.status_code != 200:
            console.print(f"[red]Invalid Ngenic refresh token: {resp.text}[/red]")
            sys.exit(1)
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
    if not ngenic_rooms:
        console.print("[red]No Ngenic rooms found.[/red]")
        sys.exit(1)
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
    console.print(Panel("[bold green]Netatmo ← Ngenic Bridge Setup Wizard (Updated Dec 2025)[/bold green]", expand=False))
    console.print("[bold yellow]Note:[/bold yellow] Netatmo password login is deprecated. We use manual token generation instead.\n")

    client_id, client_secret = create_netatmo_app()
    temp_access_token = get_netatmo_access_token_for_setup(client_id, client_secret)
    netatmo_rooms = fetch_netatmo_homes(temp_access_token)

    refresh_token_ngenic = get_ngenic_refresh_token()
    ngenic_token = get_ngenic_access_token(refresh_token_ngenic)
    ngenic_rooms = fetch_ngenic_rooms(ngenic_token)

    mapping = map_rooms(ngenic_rooms, netatmo_rooms)
    if not mapping:
        console.print("[red]No rooms mapped → exiting.[/red]")
        sys.exit(1)

    # Config now uses refresh_token for Netatmo (runtime app will handle refreshing)
    # We'll prompt for Netatmo refresh_token separately (generated same way as access_token)
    console.print(Panel("[bold blue]Netatmo Long-Lived Refresh Token[/bold blue]", expand=False))
    console.print("Now generate a refresh token the same way:")
    console.print("Repeat the 'Generate token' step → copy the [bold]refresh_token[/bold] (long one)\n")
    netatmo_refresh = Prompt.ask("Paste your Netatmo refresh_token here", password=True).strip()

    config = {
        "netatmo": {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": netatmo_refresh
        },
        "ngenic": {
            "client_id": "tune_web",
            "client_secret": "c98ead25-07d7-4a47-9bcd-7d5c6a5f20d7",
            "refresh_token": refresh_token_ngenic
        },
        "mapping": mapping
    }

    with open("/host/config.json", "w") as f:
        json.dump(config, f, indent=2)
    console.print("\n[green]✓ config.json written to host![/green]")

    # Create secret files on host (now includes netatmo_refresh_token instead of username/password)
    os.makedirs("/host/docker-secrets", exist_ok=True)
    secrets = {
        "netatmo_client_id": client_id,
        "netatmo_client_secret": client_secret,
        "netatmo_refresh_token": netatmo_refresh,
        "ngenic_refresh_token": refresh_token_ngenic
    }
    for name, value in secrets.items():
        path = f"/host/docker-secrets/{name}"
        with open(path, "w") as f:
            f.write(value + "\n")
    console.print("[green]✓ All Docker secret files created in ./docker-secrets/[/green]")

    console.print(Panel("[bold green]Setup complete![/bold green]\nNow run: [bold cyan]docker compose up -d --build[/bold cyan]", expand=False))

if __name__ == "__main__":
    main()
