#!/bin/bash

echo "start workers"
../.venv/bin/python manage.py start_workers

echo "start celery" 
../.venv/bin/celery -A home worker -l info
