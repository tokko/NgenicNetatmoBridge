#!/bin/bash
set -e  # Exit on any error

echo "=================================================="
echo " Netatmo ← Ngenic Bridge - Bootstrap for Raspberry Pi 5"
echo " (Raspberry Pi OS 64-bit Bookworm)"
echo "=================================================="
echo

# --- 1. Update system & install basics ---
echo "[1/7] Updating system and installing vim, git, wget..."
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y vim git wget ca-certificates curl gnupg lsb-release

# --- 2. Add Docker's official GPG key ---
echo "[2/7] Adding Docker GPG key..."
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# --- 3. Add Docker repository (Debian Bookworm for arm64) ---
echo "[3/7] Adding Docker repository..."
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  bookworm stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update

# --- 4. Install Docker Engine + Compose plugin ---
echo "[4/7] Installing Docker Engine and Compose plugin..."
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add current user to docker group
sudo usermod -aG docker $USER
echo "✓ Docker installed (you may need to log out/in for group changes)"

# --- 5. Initialize Docker Swarm (single-node for secrets support) ---
echo "[5/7] Initializing Docker Swarm (single-node mode)..."
if ! docker info | grep -q "Swarm: active"; then
    docker swarm init --advertise-addr $(hostname -I | awk '{print $1}')
fi
echo "✓ Swarm active"

# --- 6. Clone the repository ---
REPO_URL="https://github.com/yourusername/netatmo-ngenic-bridge.git"  # ← CHANGE TO YOUR REPO!
PROJECT_DIR="netatmo-ngenic-bridge"

echo "[6/7] Cloning repository..."
if [ -d "$PROJECT_DIR" ]; then
    echo "Directory $PROJECT_DIR already exists – pulling latest..."
    cd $PROJECT_DIR
    git pull
    cd ..
else
    git clone "$REPO_URL" "$PROJECT_DIR"
fi
cd $PROJECT_DIR

# --- 7. Build image, run setup, create secrets, launch service ---
echo "[7/7] Building Docker image..."
docker build -t netatmo-ngenic-bridge .

echo
echo "=================================================="
echo " Starting INTERACTIVE SETUP"
echo " Follow the prompts to enter credentials and map rooms"
echo "=================================================="
echo

# Run interactive setup in temporary container
docker run --rm -it \
  -v "$(pwd):/host" \
  netatmo-ngenic-bridge \
  python setup.py

echo
echo "=================================================="
echo " Creating Docker Swarm secrets from generated files..."
echo "=================================================="

for secret_file in docker-secrets/*; do
    secret_name=$(basename "$secret_file")
    if docker secret ls --filter name="$secret_name" | grep -q "^$secret_name "; then
        echo "Secret $secret_name already exists – skipping"
    else
        docker secret create "$secret_name" "$secret_file"
        echo "Created secret: $secret_name"
    fi
done

echo
echo "=================================================="
echo " Launching the service with docker compose..."
echo "=================================================="

docker compose up -d --build

echo
echo "=================================================="
echo " ALL DONE! 🎉"
echo " Your Netatmo ← Ngenic bridge is now running"
echo " API available at: http://$(hostname -I | awk '{print $1}'):8000"
echo " View logs: docker compose logs -f"
echo " Status check: curl http://localhost:8000/status"
echo "=================================================="
