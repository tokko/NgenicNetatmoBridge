import httpx
import json
import getpass
import os
import sys

def create_netatmo_app():
    print("\n=== Netatmo Developer App ===")
    print("Go to: https://dev.netatmo.com/apps/")
    print("Click 'Create an app'")
    print("Fill in any name/description, no redirect URI needed.")
    client_id = input("Enter your Netatmo Client ID: ").strip()
    client_secret = input("Enter your Netatmo Client Secret: ").strip()
    return client_id, client_secret

def get_netatmo_token(client_id, client_secret):
    print("\n=== Netatmo Login ===")
    username = input("Netatmo email: ").strip()
    password = getpass.getpass("Netatmo password: ")
    
    with httpx.Client() as client:
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
        data = resp.json()
        access_token = data["access_token"]
        print("Netatmo authentication successful!")
        return access_token, username, password

def fetch_netatmo_homes(access_token):
    print("\nFetching your Netatmo homes and rooms...")
    with httpx.Client() as client:
        resp = client.post(
            "https://api.netatmo.com/api/homesdata",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        resp.raise_for_status()
        body = resp.json()["body"]
        
        homes = body.get("homes", [])
        if not homes:
            print("No Netatmo Energy homes found (thermostat/valves).")
            sys.exit(1)
        
        netatmo_rooms = []
        for home in homes:
            home_id = home["id"]
            home_name = home.get("name", "Unnamed home")
            print(f"\nHome: {home_name} (id: {home_id})")
            for room in home.get("rooms", []):
                room_id = room["id"]
                room_name = room.get("name", "Unnamed room")
                print(f"  - Room: {room_name} (id: {room_id})")
                netatmo_rooms.append({
                    "home_id": home_id,
                    "home_name": home_name,
                    "room_id": room_id,
                    "room_name": room_name
                })
        return netatmo_rooms

def get_ngenic_refresh_token():
    print("\n=== Ngenic Tune Refresh Token ===")
    print("Instructions:")
    print("1. Open https://tune.ngenic.com in a browser and log in.")
    print("2. Open Developer Tools (F12) → Network tab")
    print("3. Refresh the page")
    print("4. Find a request to '/auth/token'")
    print("5. In the request payload, copy the long 'refreshToken' value")
    refresh_token = getpass.getpass("Paste your Ngenic refresh_token here: ").strip()
    return refresh_token

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
        return resp.json()["accessToken"]

def fetch_ngenic_rooms(access_token):
    print("\nFetching your Ngenic Tune rooms...")
    with httpx.Client() as client:
        # First get all tunes (usually only one)
        resp = client.get(
            "https://api.ngenic.com/v3/tune/tunes",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        resp.raise_for_status()
        tunes = resp.json()
        
        if not tunes:
            print("No Ngenic Tunes found.")
            sys.exit(1)
        
        ngenic_rooms = []
        for tune in tunes:
            tune_uuid = tune["uuid"]
            tune_name = tune.get("name", "My House")
            print(f"\nTune: {tune_name} (uuid: {tune_uuid})")
            
            rooms_resp = client.get(
                f"https://api.ngenic.com/v3/tune/tunes/{tune_uuid}/rooms",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            rooms_resp.raise_for_status()
            for room in rooms_resp.json():
                room_uuid = room["uuid"]
                room_name = room.get("name", "Unnamed room")
                current_temp = room.get("currentTemperature")
                print(f"  - Room: {room_name} (uuid: {room_uuid})  Current: {current_temp}°C")
                ngenic_rooms.append({
                    "room_uuid": room_uuid,
                    "room_name": room_name
                })
        return ngenic_rooms

def map_rooms(ngenic_rooms, netatmo_rooms):
    print("\n=== Room Mapping ===")
    print("Match each Ngenic room to the corresponding Netatmo room (by name or manually).")
    
    mapping = []
    for ng_room in ngenic_rooms:
        print(f"\nNgenic room: {ng_room['room_name']} (uuid: {ng_room['room_uuid']})")
        print("Available Netatmo rooms:")
        for i, nt_room in enumerate(netatmo_rooms):
            print(f"  {i+1}: {nt_room['room_name']} (home: {nt_room['home_name']}, id: {nt_room['room_id']})")
        
        choice = input("Enter number (or 'skip' to ignore this room): ").strip()
        if choice.lower() == 'skip':
            continue
        try:
            idx = int(choice) - 1
            selected = netatmo_rooms[idx]
            mapping.append({
                "ngenic_room_uuid": ng_room["room_uuid"],
                "netatmo_home_id": selected["home_id"],
                "netatmo_room_id": selected["room_id"]
            })
            print(f"→ Mapped to Netatmo {selected['room_name']}")
        except:
            print("Invalid choice, skipping.")
    return mapping

def main():
    print("Netatmo ← Ngenic Auto-Sync Bridge Setup Wizard")
    
    # Netatmo
    client_id, client_secret = create_netatmo_app()
    access_token, netatmo_username, netatmo_password = get_netatmo_token(client_id, client_secret)
    netatmo_rooms = fetch_netatmo_homes(access_token)
    
    # Ngenic
    ngenic_refresh = get_ngenic_refresh_token()
    ngenic_access = get_ngenic_access_token(ngenic_refresh)
    ngenic_rooms = fetch_ngenic_rooms(ngenic_access)
    
    # Mapping
    mapping = map_rooms(ngenic_rooms, netatmo_rooms)
    if not mapping:
        print("No mappings created. Exiting.")
        sys.exit(1)
    
    # Build config
    config = {
        "netatmo": {
            "client_id": client_id,
            "client_secret": client_secret,
            "username": netatmo_username,
            "password": netatmo_password
        },
        "ngenic": {
            "client_id": "tune_web",
            "client_secret": "c98ead25-07d7-4a47-9bcd-7d5c6a5f20d7",
            "refresh_token": ngenic_refresh
        },
        "mapping": mapping
    }
    
    # Write config.json
    with open("config.json", "w") as f:
        json.dump(config, f, indent=2)
    print("\nconfig.json created!")
    
    # Create Docker secrets (run this in your Docker host directory)
    print("\nCreating Docker secrets (save these commands or run them now):")
    secrets_dir = "docker-secrets"
    os.makedirs(secrets_dir, exist_ok=True)
    
    for key, value in [
        ("netatmo_client_id", client_id),
        ("netatmo_client_secret", client_secret),
        ("netatmo_username", netatmo_username),
        ("netatmo_password", netatmo_password),
        ("ngenic_refresh_token", ngenic_refresh)
    ]:
        secret_file = f"{secrets_dir}/{key}"
        with open(secret_file, "w") as f:
            f.write(value)
        print(f"echo '{value}' | docker secret create {key} -")
        # Or: docker secret create {key} {secret_file}
    
    print("\nAll done!")
    print("Now update your docker-compose.yml to use secrets (see below) and deploy!")

if __name__ == "__main__":
    main()
