'''
Created on 19 janv. 2026

@author: denis
'''
from django.core.management.base import BaseCommand
from modules.grbl import GRBLController, wait_for
import time


class Command(BaseCommand):
    help = "Démarre les tâches Celery."

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)
        #parser.add_argument("--task", action="store", dest="task", default='start_all')

    def handle(self, *args, **options):  # @UnusedVariable
        def check_limits(grbl):
            grbl.send("$130=")  # Limite max X
            grbl.send("$131=")  # Limite max Y

        def check_speed_limits(grbl):
            grbl.send("$110")  # Vitesse max X
            grbl.send("$111")  # Vitesse max Y
            grbl.send("$112")  # Vitesse max Z

        #task = options['task']
        try:
            grbl = GRBLController()
            grbl.send("$$")

            #print("clear_alarm")
            #grbl.clear_alarm()
            #print("home_machine")
            #grbl.home_machine()

            grbl.go_origin(feed=1000)
            wait_for(4.0)
            print("go_origin pos", grbl.get_mpos())

            #grbl.go_origin(feed=1000)
            #check_limits(grbl)


            #print("home_machine")
            #grbl.home_machine()

            print("move_to 100, 100")
            grbl.move_to(100, 100, feed=1500)
            wait_for(4.0)

            #print("halt")
            #grbl.halt()
            #wait_for(2.0)
            #print("pos", grbl.get_mpos())

            print("go_origin")
            #grbl.go_origin(feed=2000)
            grbl.move_to(0, 0, feed=3000)
            wait_for(2.0)
            print("pos", grbl.get_mpos())



        except Exception as e:
            print(e)

