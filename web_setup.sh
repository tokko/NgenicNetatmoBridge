#!/bin/bash
docker build -t netatmo-ngenic-setup .

docker run --rm --network host \
  -v "$(pwd):/host" \
  netatmo-ngenic-setup \
  uvicorn setup_web:app --host 0.0.0.0 --port 8000
