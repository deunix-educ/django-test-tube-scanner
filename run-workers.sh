#!/bin/bash

APP_DIR="/home/rpi4/PlanarianScanner"
cd "$APP_DIR/test_tube_scanner"

echo "start workers"
$APP_DIR/.venv/bin/python manage.py start_workers

echo "start celery" 
$APP_DIR/.venv/bin/celery -A home worker -l info
