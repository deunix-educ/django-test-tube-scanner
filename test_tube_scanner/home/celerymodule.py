#
# encoding: utf-8
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'home.settings')

appc = Celery('home')
appc.config_from_object('django.conf:settings', namespace='CELERY')
appc.autodiscover_tasks()
