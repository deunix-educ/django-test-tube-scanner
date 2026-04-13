'''
Created on 19 janv. 2026

@author: denis
'''
from django.core.management.base import BaseCommand
#from django.conf import settings
from scanner.tasks import export_images
from scanner.models import Configuration
    
class Command(BaseCommand):
    help = "Exporter les images jpg dans un fichier ZIP"

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)
        parser.add_argument("--uuid", type=str, help=f"Export video to jpg zip file with uuid")

    def handle(self, *args, **options):  # @UnusedVariable
        try:
            uuid = options.get('uuid')
            conf = Configuration.objects.filter(active=True).first()
            
            print(f"Export video to jpg zip file with uuid: {uuid}")
            # Export images ZIP
            job_zip = export_images(
                uuid,
                start_ts=None,
                end_ts=None,
                jpeg_quality=conf.video_jpeg_quality,   # Qualité JPEG
            )
            print()
            print(job_zip)

        except Exception as e:
            print("Export video to jpg zip file with uuid error", e)

