'''
scanner/multiwell.py
    WellIterator: Itérateur personnalisé pour naviguer dans les Wells
    MultiWellManager: Manager des multi-puits
    
Created on 20 avr. 2026

@author: denis
'''
import logging
import time
from threading import Thread, Event
#from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.utils.html import mark_safe
from django.conf import settings
from planarian.models import ExperimentConfig
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
        self.multiwel = None
        self.set_default_values()
        self.set_multiwell()
        self.scan_thread = None
        self.test_thread = None

    def set_default_values(self, feed=None, step=None, duration=None):
        self._feed = feed or self.process.conf.calibration_default_feed
        self._step = step or self.process.conf.calibration_default_step
        self._duration = duration or self.process.conf.calibration_default_duration
        self.px_per_mm = 50.0


    def set_multiwell(self, position=None):
        if position is None:
            self.multiwell = models.MultiWell.objects.filter(default=True).first()
        else:
            self.multiwell = models.MultiWell.by_position(position)
            
        wells = models.WellPosition.objects.filter(multiwell_id=self.multiwell.id).order_by('order').all()
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
        for wl in self.well_iterator:
            multiwells.append(f"""<button class="w3-button well" value="{wl.order}" onclick="goto_well(this)">{wl.well.name}</button>""")
        multiwells.append('''</div>''')
        self.well_iterator.reset()
        return mark_safe("\n".join(multiwells))         
       
        
    #def _grid_scanning_capture(self, uuid, duration):
    def _grid_scanning_capture(self, experiment, well_position, simulate=False):
        well = well_position.well
        multiwell = experiment.multiwell
        
        # Paramètres d'une expérience PlanarianScanner
        cfg = ExperimentConfig.objects.get(experiment_id=experiment.id, well_id=well.id)
        # reset PlanarianTracker => on_well_change
        self.process.cam.on_well_change(cfg)
        
        uuid = f'{self.process.data.session}-{multiwell.position}-{well.name}'
        ## start recording   
        self.process.data.uuid = uuid
        if not simulate:
            self.process.data.record = True
        
        start = time.monotonic()
        while not self.stop_playing.is_set():
            if time.monotonic() - start > multiwell.duration:
                break
            self.cnc_controller.wait_for(1.0)
            
        self.process.data.record = False
        self.process.data.uuid = None
        
        msg = f"{uuid}: capture done"
        logger.info(msg)
        self.process._send(scan_state=msg)      
               
        
    def _grid_scanning(self, experiment, xnext=0, ynext=0, simulate=False):
        multiwell = experiment.multiwell
        wells = models.WellPosition.objects.filter(multiwell_id=multiwell.id).order_by('order').all()
        cam = self.process.cam
        cam._aligner.set_tube_diameter(multiwell.diameter)    
            
        self.stop_playing = Event()
        for wl in wells:
            if self.stop_playing.is_set():
                break
            self.cnc_controller.move_to(wl.x, wl.y, feed=wl.multiwell.feed)  
            self._grid_scanning_capture(experiment, wl, simulate=simulate)
            
            ## change file 
            if self.process.conf.capture_type == 'file':
                self.process.cam._error_occured = True            
            
        logger.info(f"Scan terminé — retour à l'origine (X={xnext:.1f}  Y={ynext:.1f})")
        self.cnc_controller.move_to(xnext, ynext, feed=multiwell.feed*2)
             

    def _start_scanning(self, session, experiments, simulate=False):
        self.process.cam._aligner.debug = False
        xynext = []
        for obs in experiments:
            xynext.append((obs.multiwell.xbase, obs.multiwell.ybase))
        xynext.append((0, 0))

        pos = 1
        self.process.data.session = session.id
        started = timezone.now()
        for obs in experiments:
            if self.stop_playing.is_set():
                break
            obs.started = timezone.now()
            obs.save()
            xnext, ynext = xynext[pos]
            pos +=1
            self._grid_scanning(obs, xnext=xnext, ynext=ynext, simulate=simulate)
            obs.finished = timezone.now()
            obs.save()
            
        session.finished = timezone.now()
        if self.stop_playing.is_set():
            msg = f"Session {session.name} abandonnée à {session.finished} après {session.finished - started} secondes."
        else:
            if not simulate:
                session.active = False
                if session.scanning_task:
                    session.scanning_task.enabled = False
                session.save()
            
            msg = f"Session {session.name} terminée à {session.finished} après {session.finished - started} secondes."
        logger.info(msg)
        self.process._send(scan_state=msg)
        self.scan_thread = None


    def halt_scanning(self):
        self.process.data.record = False
        self.stop_playing.set()
        self.well_iterator.reset()
        self.process.cam._aligner.debug = False   

         
    def scanning(self, sid, simulate=False):
        try:
            if self.scan_thread:
                return
            session = models.Session.objects.get(pk=sid)
            experiments = models.SessionExperiment.experiment_by_session(sid)
            self.scan_thread = Thread(target=self._start_scanning, args=(session, experiments, simulate, ), daemon=True).start()
        except Exception as e:
            print("MultiWellManager::scan error", e)       


    def previous_well(self):
        wl = self.well_iterator.previous()
        self.cnc_controller.move_to(wl.x, wl.y, feed=wl.multiwell.feed)
        return {"state": "previous", "msg": f">>> ({wl.x}, {wl.y})"} 
     
     
    def next_well(self):
        wl = self.well_iterator.next()
        self.cnc_controller.move_to(wl.x, wl.y, feed=wl.multiwell.feed)
        return {"state": "next", "msg": f">>> ({wl.x}, {wl.y})"} 
    
    
    def goto_well(self, numwell):
        wl = self.well_iterator.seek(numwell)
        self.cnc_controller.move_to(wl.x, wl.y, feed=wl.multiwell.feed)
        return {"state": "goto", "msg": f">>> ({wl.x}, {wl.y})"}    
    
    
    def set_well_position(self):
        wl = self.well_iterator.get_current()
        if wl:
            wl.x, wl.y = self.cnc_controller.get_mpos()
            wl.save()
            if wl.order == 0:
                models.MultiWell.objects.filter(position__exact=wl.multiwell.position).update(xbase=wl.x, ybase=wl.y)
            return {"state": "well_position", "msg": f">>> saved ({wl.x}, {wl.y})"}
        return {"state": "well_position", "msg": f">>> pas de puit"}
                                   

    def _scanning_test(self, auto=False):       
        self.stop_playing = Event()
        cam = self.process.cam
        cam._aligner.set_tube_diameter(self.multiwell.diameter)
        duration = self.duration if not auto else settings.CALIBRATION_AUTO_DURATION        
        try:
            start_test = time.monotonic()  
            for wl in self.well_iterator:
                if self.stop_playing.is_set():
                    break
                self.cnc_controller.wait_for(2.0)
                self.cnc_controller.move_to(wl.x, wl.y, feed=wl.multiwell.feed)
                self.process._send(current=wl.order)
    
                start = time.monotonic()
                while not self.stop_playing.is_set():
                    if time.monotonic() - start > duration:
                        break
                    
                    if auto:
                        msg = cam.align_detection["msg"]
                        if cam.align_detection.get('detected'):

                            if cam.align_detection.get('action')=="grbl":
                                self.cnc_controller.wait_for(settings.CALIBRATION_AUTO_TIMEOUT)
                                dx_mm, dy_mm = cam.align_detection["offset_x_mm"], cam.align_detection["offset_y_mm"]
                                
                                self.cnc_controller.move_to(self.cnc_controller.x + dx_mm, self.cnc_controller.y + dy_mm, feed=150)
                                self.process._send(state='center', msg=msg)
                                
                            elif cam.align_detection.get('action') in ['none']:
                                msg = f"Ok centre trouvé. {msg}"
                                logger.info(msg)
                                self.process._send(state='save', msg=msg)
                                wl.x, wl.y = self.cnc_controller.x, self.cnc_controller.y
                                wl.px_per_mm = cam.align_detection.get('px_per_mm')
                                wl.save()
                                if wl.order == 0:
                                    models.MultiWell.objects.filter(position__exact=self.position).update(xbase=wl.x, ybase=wl.y)
                                break
                        else:
                            logger.info(msg)
                            self.process._send(state='center', msg=msg)

                    self.cnc_controller.wait_for(0.1)
            logger.info("Fin du centrage")        
        except Exception as e:
            print(e)
              
        self.well_iterator.reset()
        self.process.cam._aligner.debug = False

        logger.info(f"Scan terminé — retour à l'origine (X=0, Y=0) en {int(time.monotonic()-start_test)} s")
        self.cnc_controller.move_to(0, 0, feed=self.multiwell.feed*2)
        self.test_thread = None
        
        
    def scan_test(self, auto=False):
        if self.test_thread:
            return
        self.test_thread = Thread(target=self._scanning_test, args=(auto, ), daemon=True).start()


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


    def get_well_order(self):
        wl = self.well_iterator.get_current() 
        if wl:
            return wl.order
        return None


    def set_position(self):
        x, y = self.cnc_controller.get_mpos()
        self.cnc_controller.wait_for(2.0)
        models.MultiWell.objects.filter(position__exact=self.position).update(xbase=x, ybase=y)
        self._xbase, self._ybase = x, y
        wl = self.well_iterator.seek(0)  # base puit 0
        wl.x, wl.y = x, y
        wl.px_per_mm = self.px_per_mm
        wl.save()

        
    def calib_toggle_debug(self):
        """    Active / désactive le mode debug sur le stream."""
        aligner = self.process.cam._aligner
        aligner.debug = not aligner.debug       
        return {"state": "debug", "msg": f"Debug: {aligner.debug}"}
    
    def set_calib_debug(self, value=True):
        """    Active / désactive le mode debug sur le stream."""
        aligner = self.process.cam._aligner
        aligner.debug = value      
        return {"state": "debug", "msg": f"Debug: {aligner.debug}"}    
    
    
