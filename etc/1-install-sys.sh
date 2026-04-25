!/bin/bash

echo "==== System installation for rpi"
echo

sudo apt update
sudo apt upgrade

ETC="$(pwd)"

mkdir -p $HOME/exports
mkdir -p$HOME/medias
mkdir -p /mnt/exports

cp ../test_tube_scanner/.env.example ../test_tube_scanner/.env
echo "==== Copie .env ==> MODIFIER CE FICHIER POUR POUVOIR cONTINUER"
echo

# system
echo "==== system essential"
sudo apt -y install build-essential openssl git pkg-config redis supervisor sqlitebrowser samba-client cifs-utils gettext

echo "==== python3 install"
sudo apt -y install python3-dev python3-pip python3-venv libpq-dev default-libmysqlclient-dev libmariadb-dev python3-picamera2

echo "==== supervisor http access login:pass => root:toor"
sudo cp supervisor-inet_http.conf /etc/supervisor/conf.d/
sudo ln -s $ETC/scanner_service.conf /etc/supervisor/conf.d/
sudo ln -s $ETC/reductstore_service.conf /etc/supervisor/conf.d/

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
