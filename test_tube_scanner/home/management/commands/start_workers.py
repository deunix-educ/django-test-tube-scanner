'''
Created on 19 janv. 2026

@author: denis
'''
from django.core.management.base import BaseCommand
from scanner import tasks as scanner_tasks



class Command(BaseCommand):
    help = "Démarre les tâches Celery."

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)
        #parser.add_argument("--task", action="store", dest="task", default='start_all')

    def handle(self, *args, **options):  # @UnusedVariable
        #task = options['task']
        try:

            scanner_tasks.scanner_start.delay()   # @UndefinedVariable
            scanner_tasks.replay_start.delay()   # @UndefinedVariable
        except Exception as e:
            print(e)

