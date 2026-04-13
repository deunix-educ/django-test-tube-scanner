'''
Created on 19 janv. 2026

@author: denis
'''
from django.core.management.base import BaseCommand
#from django.conf import settings
from scanner.tasks import export_videos
from scanner.models import Configuration
    
class Command(BaseCommand):
    help = "Exporter les videos"

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)
        parser.add_argument("--uuid", type=str, help=f"Export video")
 
    def handle(self, *args, **options):  # @UnusedVariable
        try:
            uuid = options.get('uuid')
            conf = Configuration.objects.filter(active=True).first()
            
            print(f"Export video uuid: {uuid}", conf)
            job = export_videos( 
                uuid,
                start_ts=None,
                end_ts=None,
                frame_rate=conf.video_frame_rate,                  # Frame rate de la vidéo exportée
                opencv_fourcc_format=conf.opencv_fourcc_format,    # Format de compression vidéo (ex: 'mp4v' pour MP4),
                opencv_video_type=conf.opencv_video_type,          # Type de vidéo exportée (ex: 'mp4', 'avi', 'mkv'),               
            
            )
            print()          
            print(f"Export video: {job.id}")
        except Exception as e:
            print("Export video uuid error", e)

