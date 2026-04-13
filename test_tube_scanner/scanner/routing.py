#
# routing.py
from django.urls import re_path
from django.conf import settings
from . import consumers

urla = settings.SCANNER_WEBSOCKET_ROUTE
urlb = settings.REPLAY_WEBSOCKET_ROUTE

websocket_urlpatterns = [
    re_path(urla, consumers.ScannerConsumer.as_asgi()),
    re_path(urlb, consumers.ReplayConsumer.as_asgi()),
]