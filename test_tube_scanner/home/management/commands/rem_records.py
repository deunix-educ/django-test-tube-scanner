'''
Created on 19 janv. 2026

@author: denis
'''
import asyncio
from django.core.management.base import BaseCommand
from scanner.export_tasks import remove_video_by_uuid
from scanner.models import MultiWell


async def remove_video(sid, multiwells):
    for m in multiwells:
        row_to_char = m.row_order.split(',')
        for row in range(m.rows):
            for col in range(m.cols):
                uuid = f'{sid}-{m.position}-{row_to_char[row]}{col+1}'
                filters = {"$and": [{"&session": { "$eq": sid} }]}
                print(f"Delete video for {uuid} with filters {filters}")
                await remove_video_by_uuid(uuid, when=filters)


class Command(BaseCommand):
    help = "Démarre les tâches Celery."

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)
        parser.add_argument("--session", type=int, default=0, help=f"Delete all videos from Session id")

    def handle(self, *args, **options):  # @UnusedVariable
        try:
            sid = options.get('session')
            multiwels = [m for m in  MultiWell.objects.filter(active=True).all() ]
            asyncio.run(remove_video(sid, multiwels))

        except Exception as e:
            print("Delete all videos from Session error", e)

