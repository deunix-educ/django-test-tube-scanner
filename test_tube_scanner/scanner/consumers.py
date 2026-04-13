#
#from django.utils.translation import gettext_lazy as _
#from channels.layers import get_channel_layer
#from django.conf import settings
#import asyncio
#from asgiref.sync import sync_to_async
import json, logging
from channels.generic.websocket import AsyncWebsocketConsumer

from .process import redisDB

logger = logging.getLogger(__name__)

class ScannerConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.this_group = f"scanner_proc"
        await self.channel_layer.group_add(self.this_group, self.channel_name)
        await self.accept()
        logger.info(f"==== connected to {self.this_group}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.this_group, self.channel_name)
        logger.info( f"==== Disconnect from {self.this_group}")

    async def scanner_message(self, event):
        await self.send(text_data=json.dumps(event["text"]))

    ## Receive message from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type  = data.get("type")
        if msg_type in ["scanner", "calibrate"]:
            redisDB.publish(self.this_group, json.dumps(data))

    async def replay_message(self, event):
        await self.send(text_data=json.dumps(event["text"]))


class ReplayConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.this_group = f"replay_proc"
        await self.channel_layer.group_add(self.this_group, self.channel_name)
        await self.accept()
        logger.info(f"==== connected to {self.this_group}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.this_group, self.channel_name)
        logger.info( f"==== Disconnect from {self.this_group}")

    async def replay_message(self, event):
        await self.send(text_data=json.dumps(event["text"]))


    ## Receive message from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type  = data.get("type")
        if msg_type == "replay":
            redisDB.publish(self.this_group, json.dumps(data))

