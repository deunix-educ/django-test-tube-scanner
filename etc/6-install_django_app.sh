#!/bin/bash
# Script d'installation de l'application'

# Mise à jour des paquets
echo "installation de l'application django ..."
echo

ETC="$(pwd)"
APP_DIR=" ../test_tube_scanner"

cd $APP_DIR

echo "migration de la base de données ..."
./manage.py migrate
./manage.py makemigrations
./manage.py migrate

echo "User / django_celery_beat ..."
./manage.py init_data

echo "Tables ..."
./manage.py loaddata $ETC/db/configuration.json 
./manage.py loaddata $ETC/db/well.json 
./manage.py loaddata $ETC/db/multiwell.json 
./manage.py loaddata $ETC/db/welposition.json 


echo 
echo "=== Installation terminée ==="
echo


