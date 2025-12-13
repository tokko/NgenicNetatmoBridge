docker build -t netatmo-ngenic-autosync .
docker run -d --name netatmo-sync -p 8000:8000 --restart unless-stopped netatmo-ngenic-autosync
