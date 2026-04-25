#!/bin/bash
# Script d'installation de l'application'

# Mise à jour des paquets
echo "installation de l'application django ..."
echo

ETC="$(pwd)"
APP_DIR=" ../test_tube_scanner"

echo "---- Lancer reductstore ..."
sudo supervisorctl reread
sudo supervisorctl restart reductstore

cd $APP_DIR

echo "---- Création des répertoires media ..."
mkdir -p $APP_DIR/media/images $APP_DIR/media/simulation
mkdir -p $APP_DIR/logs
touch $APP_DIR/logs/celery.log $APP_DIR/logs/test_tube.log 

echo "---- Migration de la base de données ..."
./manage.py migrate
./manage.py makemigrations
./manage.py migrate

echo "---- User / django_celery_beat ..."
./manage.py init_data

echo "---- Tables ..."
./manage.py loaddata $ETC/db/configuration.json 
./manage.py loaddata $ETC/db/well.json 
./manage.py loaddata $ETC/db/multiwell.json 

echo "---- start test_tube:*"
echo
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart test_tube:*

echo 
echo "=== Installation terminée ==="
echo


