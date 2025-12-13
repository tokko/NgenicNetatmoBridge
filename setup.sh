docker build -t netatmo-ngenic-setup .

docker run --rm -it \
  -v "$(pwd):/host" \
  netatmo-ngenic-setup \
  python setup.py
