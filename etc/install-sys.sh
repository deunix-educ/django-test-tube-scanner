!/bin/bash

echo "==== System installation for rpi 4/5"
echo

sudo apt update
#sudo apt upgrade

# system
echo "==== system essential"
sudo apt -y install build-essential openssl git pkg-config redis supervisor sqlitebrowser samba-client cifs-utils

echo "==== python3 install"
sudo apt -y install python3-dev python3-pip python3-venv default-libmysqlclient-dev libmariadb-dev libpq-dev python3-picamera2

echo "==== supervisor http access config"
sudo cp supervisor-inet_http.conf /etc/supervisor/conf.d/
sudo ln -s scanner_service.conf /etc/supervisor/conf.d/
sudo ln -s reductstore_service.conf /etc/supervisor/conf.d/

echo "==== restart supervisor "
sudo systemctl restart supervisor

echo "==== python env with system site packages for picamera2"
rm -rf ../.venv
python -m venv --system-site-packages ../.venv
source ../.venv/bin/activate

echo "==== pip requirements"
pip install -r ./requirements.txt

echo "==== restart services if possible"
sudo supervisorctl reread && sudo supervisorctl update

echo "==== End "
echo
