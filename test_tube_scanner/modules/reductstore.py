'''
Created on 21 août 2024

@author: denis
'''
import logging
import asyncio
from typing import Union
from abc import ABC
from reduct import Client, Bucket, BucketSettings   #, QuotaType
from reduct.time import unix_timestamp_from_any, TIME_PRECISION #, unix_timestamp_to_datetime
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ReductStoreBase(ABC):

    def __init__(self, url, api_token, name, quota_type=None, quota_size=1000_000_000):
        self.bucket_name = name
        self.client = Client(url, api_token=api_token)
        self.quota_type = quota_type
        self.quota_size = quota_size
        self.bucket: Bucket = asyncio.run(self.create_bucket())
        logger.info(f"====  {url} token:{api_token}")


    async def create_bucket(self):
        settings = BucketSettings(
            quota_type=self.quota_type,
            quota_size=self.quota_size,
            exist_ok=True,
        )
        return await self.client.create_bucket(self.bucket_name, settings, exist_ok=True)


    async def change_bucket(self, **settings):
        new_settings = BucketSettings(**settings)
        await self.bucket.set_settings(new_settings)


    async def remove_bucket(self):
        await self.bucket.remove()


    async def write(self, entry_name, data, timestamp=None, content_type=None, labels=None):
        await self.bucket.write(entry_name, data, timestamp=timestamp, content_type=content_type, labels=labels)


    def query(self, entry_name, start, stop, ttl=None, when=None):
        return self.bucket.query(entry_name, start=start, stop=stop, ttl=ttl, when=when)


    async def remove_query(self, entry_name, start, stop, when=None):
        return await self.bucket.remove_query(entry_name, start=start, stop=stop, when=when)


    async def read(self, entry_name, timestamp, head=False):
        async with self.bucket.read(entry_name, timestamp=timestamp, head=head) as record:
            return await record.read_all()


    async def record_content(self, entry_name, timestamp, head=False):
        async with self.bucket.read(entry_name, timestamp=timestamp, head=head) as record:
            content = await record.read_all()
            return record, content


class ReductStore(ReductStoreBase):
    def __init__(self, name):
        super().__init__(settings.REDUCTSTORE_URL, settings.REDUCTSTORE_TOKEN, name=name)


async def old_last_dates(client_db, entry_name='uuid'):
    oldest, latest = 0, 0
    infos = await client_db.bucket.get_entry_list()
    for info in infos:
        if info.name == entry_name:
            oldest, latest = info.oldest_record, info.latest_record
            break
    return oldest, latest


async def date_posterior_to(client_db, uuid: str, post: Union[int, str]):
    last = None
    oldest, latest = await old_last_dates(client_db, uuid)
    if oldest and post:
        dtpost = timezone.now() - timedelta(seconds=int(post))
        ts = unix_timestamp_from_any(dtpost)
        last = ts if ts < latest else None
    return oldest, last


async def dates_filter(client_db, uuid: str, begin: Union[int, datetime, float, str],
                       end: Union[int, datetime, float, str] = None, duration: int = 0):
    oldest, latest = await old_last_dates(client_db, uuid)

    ts_from, ts_to = 0, 0
    if latest:
        ts_from = unix_timestamp_from_any(begin) if begin else oldest
        if ts_from < oldest:
            ts_from = oldest

        if end is None:
            if not duration:
                ts_to = latest
            else:
                ts_to = ts_from + (duration * TIME_PRECISION)
                if ts_to > latest:
                    ts_to = latest
        else:
            ts_to = unix_timestamp_from_any(end) if end else latest
            if ts_to > latest:
                ts_to = latest

    return ts_from, ts_to if ts_from<ts_to else latest



