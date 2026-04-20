'''
Created on 20 avr. 2026

@author: denis
'''
import logging
import time
from django.utils.translation import gettext_lazy as _
from threading import Thread, Event
from django.utils import timezone
from django.utils.html import mark_safe
from modules import grbl
from . import models


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WellIterator:
    """Itérateur personnalisé pour naviguer dans les Wells"""
    
    def __init__(self, wells_queryset):
        self.wells = list(wells_queryset)  # Convertir en liste
        self.current_index = -1
        self.total_count = len(self.wells)
    
    def __iter__(self):
        """Permet d'utiliser l'itérateur dans une boucle for"""
        return self
    
    def __next__(self):
        """Retourne l'élément suivant"""
        self.current_index += 1
        if self.current_index >= self.total_count:
            raise StopIteration
        return self.wells[self.current_index]
    
    def next(self):
        """Méthode next() pour avancer manuellement"""
        if self.current_index + 1 < self.total_count:
            self.current_index += 1
            return self.wells[self.current_index]
        raise StopIteration("Fin de la liste atteinte")
    
    def previous(self):
        """Méthode previous() pour revenir en arrière"""
        if self.current_index > 0:
            self.current_index -= 1
            return self.wells[self.current_index]
        raise StopIteration("Début de la liste atteint")
    
    def seek(self, index):
        """Méthode seek() pour sauter à un index spécifique"""
        if 0 <= index < self.total_count:
            self.current_index = index
            return self.wells[index]
        raise IndexError(f"Index {index} hors limites (0-{self.total_count - 1})")
    
    def get_current(self):
        """Retourne l'élément courant"""
        if -1 < self.current_index < self.total_count:
            return self.wells[self.current_index]
        return None
    
    def reset(self):
        """Réinitialise l'itérateur au début"""
        self.current_index = -1


class MultiWellManager:

    def __init__(self, process):
        self.process = process
        self.cnc_controller = process.grbl
        self.stop_playing = Event()
        self.well_iterator = None
        
        self.scanner = None
        
        self.multiwel = None
        self.set_default_values()
        self.set_multiwell()


    def set_default_values(self, feed=None, step=None, duration=None):
        self._feed = feed or self.process.conf.calibration_default_feed
        self._step = step or self.process.conf.calibration_default_step
        self._duration = duration or self.process.conf.calibration_default_duration


    def set_multiwell(self, position=None):
        if position is None:
            self.multiwell = models.MultiWell.objects.filter(default=True).first()
        else:
            self.multiwell = models.MultiWell.by_position(position)
            
        wells = models.WellPostion.objects.filter(multiwell_id=self.multiwell.id).order_by('order').all()
        self.well_iterator = WellIterator(wells)
        
        self.position = self.multiwell.position
        self._xbase = self.multiwell.xbase
        self._ybase = self.multiwell.ybase       
        self._dx = self.multiwell.dx
        self._dy = self.multiwell.dy
        return self.multiwell.config()
    
    
    def multiwell_buttons(self):
        multiwells = []
        multiwells.append('''<div class="w3-border well-btn">''')
        for w in self.well_iterator:
            multiwells.append(f"""<button class="w3-button well" value="{w.order}" onclick="goto_well(this)">{w.well.name}</button>""")
        multiwells.append('''</div>''')
        self.well_iterator.reset()
        return mark_safe("\n".join(multiwells))         
       
        
    def _grid_scanning_capture(self, uuid, duration):
        self.process.data.uuid = uuid
        self.process.data.record = True

        start = time.monotonic()
        while not self.stop_playing.is_set():
            if time.monotonic() - start > duration:
                break
            self.cnc_controller.wait_for(1.0)

        logger.info(f"Arrêter l'enregistrement {uuid}")
        self.process.data.record = False
        self.process.data.uuid = None
        
        
    def _grid_scanning(self, observation, xnext=0, ynext=0):
        multiwell = observation.multiwell
        wells = models.WellPostion.objects.filter(multiwell_id=multiwell.id).order_by('order').all()
        
        self.stop_playing = Event()
        for w in wells:
            if self.stop_playing.is_set():
                break
            self.cnc_controller.move_to(w.x, w.y, feed=w.multiwell.feed)  
            
            uuid = f'{self.process.data.session}-{multiwell.position}-{w.well.name}'
            self._grid_scanning_capture(uuid, multiwell.duration)
            
        logger.info(f"Scan terminé — retour à l'origine (X={xnext:.1f}  Y={ynext:.1f})")
        self.cnc_controller.move_to(xnext, ynext, feed=multiwell.feed*2)
             

    def _start_scanning(self, session, observations):
        xynext = []
        for obs in observations:
            xynext.append((obs.multiwell.xbase, obs.multiwell.ybase))
        xynext.append((0, 0))

        pos = 1
        self.process.data.session = session.id
        started = timezone.now()
        for obs in observations:
            obs.started = timezone.now()
            obs.save()

            xnext, ynext = xynext[pos]
            pos +=1
            self._grid_scanning(obs, xnext=xnext, ynext=ynext)

            obs.finished = timezone.now()
            obs.save()
        session.finished = timezone.now()
        session.active = False
        session.scanning_task.enabled = False
        session.save()
        logger.info(f"==== Session {session.name} terminée à {session.finished} après {session.finished - started} secondes.")


    def halt_scanning(self):
        self.process.data.record = False
        return self.stop_playing.set()   
    
         
    def scanning(self, sid):
        try:
            session = models.Session.objects.get(pk=sid)
            observations = models.SessionObservation.observation_by_session(sid)
            Thread(target=self._start_scanning, args=(session, observations, ), daemon=True).start()
        except Exception as e:
            print("MultiWellManager::scan error", e)       


    def previous_well(self):
        w = self.well_iterator.previous()
        self.cnc_controller.move_to(w.x, w.y, feed=w.multiwell.feed)
        return {"state": "previous", "msg": f">>> ({w.x}, {w.y})"} 
     
     
    def next_well(self):
        w = self.well_iterator.next()
        self.cnc_controller.move_to(w.x, w.y, feed=w.multiwell.feed)
        return {"state": "next", "msg": f">>> ({w.x}, {w.y})"} 
    
    
    def goto_well(self, numwell):
        w = self.well_iterator.seek(numwell)
        self.cnc_controller.move_to(w.x, w.y, feed=w.multiwell.feed)
        return {"state": "goto", "msg": f">>> ({w.x}, {w.y})"}    
    
    
    def set_well_position(self):
        w = self.well_iterator.get_current()
        w.x, w.y = self.cnc_controller.get_mpos()
        w.save()
        return {"state": "well_position", "msg": f">>> saved ({w.x}, {w.y})"}   


    def _scanning_test(self, xnext=0, ynext=0):       
        self.stop_playing = Event()
        for w in self.well_iterator:
            if self.stop_playing.is_set():
                break
            self.cnc_controller.move_to(w.x, w.y, feed=w.multiwell.feed)
            
            start = time.monotonic()
            while not self.stop_playing.is_set():
                if time.monotonic() - start > self.duration:
                    break
                self.cnc_controller.wait_for(1.0)
    
            logger.info(f"Arrêter la simulation")            
            
        self.well_iterator.reset()
            
        logger.info(f"Scan terminé — retour à l'origine (X={xnext:.1f}  Y={ynext:.1f})")
        self.cnc_controller.move_to(xnext, ynext, feed=self.multiwell.feed*2)
        
        
    def scan_test(self):
        Thread(target=self._scanning_test, daemon=True).start()


    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = value
        
    @property
    def duration(self):
        return self._duration

    @duration.setter
    def duration(self, value):
        self._duration = value
        
    @property
    def step(self):
        return self._step

    @step.setter
    def step(self, value):
        self._step = value

    @property
    def feed(self):
        return self._feed

    @feed.setter
    def feed(self, value):
        self._feed = value

    @property
    def xbase(self):
        return self._xbase

    @xbase.setter
    def xbase(self, value):
        self._xbase = value

    @property
    def ybase(self):
        return self._ybase

    @ybase.setter
    def ybase(self, value):
        self._ybase = value

    @property
    def dx(self):
        return self._dx

    @dx.setter
    def dx(self, value):
        self._dx = value

    @property
    def dy(self):
        return self._dy

    @dy.setter
    def dy(self, value):
        self._dy = value


    def set_xy_step(self):
        models.MultiWell.objects.filter(position__exact=self.position).update(dx=self.dx, dy=self.dy)


    def set_position(self):
        x, y = self.cnc_controller.get_mpos()
        self.cnc_controller.wait_for(2.0)
        models.MultiWell.objects.filter(position__exact=self.position).update(xbase=x, ybase=y)
        self._xbase, self._ybase = x, y

        
    def calib_toggle_debug(self):
        """    Active / désactive le mode debug sur le stream."""
        aligner = self.process.cam._aligner
        aligner.debug = not aligner.debug       
        return {"state": "debug", "msg": f"Debug: {aligner.debug}"}     
