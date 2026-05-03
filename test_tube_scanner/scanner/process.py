# process.py
import os
os.environ['OPENCV_LOG_LEVEL']="0"
os.environ['OPENCV_FFMPEG_LOGLEVEL']="0"
import cv2

from django.utils.translation import gettext_lazy as _
from datetime import datetime
import time, asyncio, bisect
import json, base64
from threading import Thread, Event, Lock
from queue import Queue
from asgiref.sync import async_to_sync  #, sync_to_async
from channels.layers import get_channel_layer

from django.utils import timezone
from django.conf import settings

from celery import Task
from celery.exceptions import Ignore
from celery.utils.log import get_task_logger
from redis import Redis
from dataclasses import dataclass
from modules import reductstore, grbl, utils

## camera devices
from modules.circular_crop import CircularCrop, CropStrategy
from .multiwell import MultiWellManager
from .constants import ScannerConstants
from . import models


@dataclass
class ProcessData:
    play: bool = True
    record: bool = False
    uuid: str = None
    session: int = 0
    tube_diameter: float = 16.0 


logger = get_task_logger(__name__)
redisDB = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, decode_responses=True)
cameraDB = reductstore.ReductStore(name='camera')


class CameraRecordManager():

    def __init__(self, clienDB):
        self.clienDB = clienDB
        self.is_image = False
        self.oldest_ts = None
        self.latest_ts = None

    async def size(self, uuid, start_ts, end_ts):
        try:
            queries = self.query(uuid, start_ts, end_ts)
            total_size = 0
            record_number = 0
            latest = None
            async for record in queries:
                if not record_number:
                    self.oldest_ts = record.timestamp

                frame_bytes = await record.read_all()
                total_size += len(frame_bytes)
                record_number += 1
                latest = record.timestamp
            self.latest_ts = latest

            return total_size
        except:
            return None

    def black_jpg(self):
        frame = cv2.imread(settings.MEDIA_ROOT / 'images' / 'black-screen.jpg', cv2.IMREAD_UNCHANGED)
        _, frame = cv2.imencode('.jpg', frame)
        black_jpg = frame.tobytes()
        return f'data:image/jpeg;base64,{base64.b64encode(black_jpg).decode()}'

    def set_filters(self, session=None, test=None):
        filters = []
        if session:
            filters.append({"&session": { "$eq": session} })
        if test==True:
            filters.append({"&test": { "$contains": "True"} })

        when = {"$and": filters}
        return when

    async def record_content(self, query):
        record = await anext(query)
        content = await record.read_all()
        return record, content

    def query(self, uuid, start=None, stop=None, filters=None):
        try:
            return self.clienDB.query(uuid, start, stop, when=filters, ttl=3600)
        except Exception as e:
            logger.error(f"CameraRecordManager query: {e}")

    def first_image(self, uuid, start=None, stop=None, filters=None):
        try:
            query = self.query(uuid, start, stop, filters=filters)
            record, content = async_to_sync(self.record_content)(query)
            self.is_image = True
            return f'data:image/jpeg;base64,{base64.b64encode(content).decode()}', record.timestamp

        except Exception as e:  # @UnusedVariable
            pass
            #logger.error(f"CameraRecordManager first_image: {e}")
        self.is_image = False
        return self.black_jpg(), start

    def write(self, uuid, frame, labels, ts=None):
        try:
            if ts is None:
                ts = timezone.now()
            async_to_sync(self.clienDB.write)(
                uuid,
                frame,
                timestamp=ts,
                labels=labels,
                content_type='application/octet-stream',
            )
        except Exception as e:
            logger.error(f"CameraRecordManager write: {e}")


    async def remove_uuid(self, uuid, start=None, stop=None, when=None):
        try:
            await self.clienDB.remove_query(uuid, start, stop, when=when)
        except Exception as e:
            logger.error(f"CameraRecordManager remove: {e}")

    def remove(self, uuid, start=None, stop=None, when=None):
        asyncio.run(self.remove_uuid(uuid, start, stop, when=when))



class ScannerProcess(Task):
    name='scanner.scanner_process'
    def __init__(self):
        super().__init__()
        
        self.channel_layer = get_channel_layer()
        self.group = 'scanner_proc'
        self.stop_event = Event()
        self.cam = None
        self.grbl = None
        self.crop = None
        self.conf = None
        self.record_queue = Queue()
        self.data = ProcessData()
        self.manager = None
        self.recordDB = CameraRecordManager(cameraDB)

    def __call__(self, *args, **kwargs):
        return self.start(*args, **kwargs)
    
    def set_crop_radius(self, radius):
        return CircularCrop(radius=radius, strategy=CropStrategy.CROP_JPEG, jpeg_quality=self.image_quality)

    def start(self, *args, **kwargs):
        try:            
            self.conf = ScannerConstants().get()
            self.use_tracking = self.conf.tracking
            
            self.video_quality = self.conf.video_jpeg_quality
            self.image_quality = self.conf.image_quality
            self.video_fps = self.conf.video_frame_rate
            self.video_width = self.conf.video_width_capture
            self.video_height = self.conf.video_height_capture    
            self.crop_radius = self.conf.calibration_crop_radius

            self.video_jpg_quality = [int(cv2.IMWRITE_JPEG_QUALITY), self.video_quality]
            self.image_jpg_quality = [int(cv2.IMWRITE_JPEG_QUALITY), self.image_quality]
            self.grbl_xmax = self.conf.grbl_xmax
            self.grbl_ymax = self.conf.grbl_ymax
                    
            self.crop = self.set_crop_radius(self.crop_radius)
            
            capture_type = self.conf.capture_type
            if capture_type == 'file':
                video_lists = []
                wells = models.Well.objects.all()
                for wl in wells:
                    video_lists.append(str( settings.MEDIA_ROOT / 'simulation' / f'{wl.name}.mp4') )
                    
                
                from modules.videofile_capture import VideoFileCapture
                self.cam = VideoFileCapture(
                    video_file=settings.MEDIA_ROOT / 'simulation' / 'D6.mp4',
                    fps=self.video_fps,
                    width=self.video_width,
                    height=self.video_height,
                    jpeg_quality=self.video_quality,
                    use_tracking=self.use_tracking,
                    display=self._display,
                    parent=self,
                    video_lists=video_lists,
                )           
            elif capture_type == 'webcam':
                from modules.webcam_capture import WebcamCapture
                self.cam = WebcamCapture(
                    device_index=self.conf.webcam_device_index,
                    fps=self.video_fps,
                    width=self.video_width,
                    height=self.video_height,
                    jpeg_quality=self.video_quality,
                    use_tracking=self.use_tracking,
                    display=self._display,
                    parent=self,
                )
            else:
                from modules.picamera2_capture import PiCamera2Capture
                self.cam = PiCamera2Capture(
                    fps=self.video_fps,
                    width=self.video_width,
                    height=self.video_height,
                    jpeg_quality=self.video_quality,
                    use_tracking=self.use_tracking,
                    display=self._display,
                    parent=self,
                )
            
            self.cam.set_frame_callback(self._on_frame)
            self.cam._active_median = False
            self.cam.set_circular_crop(None)
            
            self.grbl = grbl.GRBLController(
                send_callback=self._display, 
                x_max=self.conf.grbl_xmax, 
                y_max=self.conf.grbl_ymax
            )

            self.stop_event.clear()
            self.start_services()
            
            return self.name
        except Exception as e:
            logger.error(f"Scanner started error: {e}")
            raise Ignore()

    def stop(self):
        try:
            info = 'Scanner stopped'
            self._send(state='stop', msg=info)
            self.stop_event.set()
            self.cam.stop()
            logger.info(info)
            Event().wait(1.0)
        finally:
            self.stop_event.set()

    def start_services(self):
        Thread(target=self._listen_to_redis, daemon=True).start()
        Thread(target=self._recording, daemon=True).start()
        Thread(target=self._init_grbl, daemon=True).start()
        self.cam.start()
        logger.warning(f"Scanner services started ...")

    def _send(self, **payload):
        async_to_sync(self.channel_layer.group_send)(
            self.group, {
                "type": 'scanner.message',
                "text": payload
            }
        )

    def _display(self, **msg):
        if self.grbl:
            self._send(**msg)

    def _on_frame(self, jpeg_bytes: bytes, ts: datetime, metrics: dict, frame_count: int = 0) -> None:
        if self.data.record:
            self.record_queue.put((self.data.uuid, ts, jpeg_bytes, metrics, frame_count))
        if self.data.play:
            try:
                jpeg=base64.b64encode(jpeg_bytes).decode()
                #logger.warning(f"{jpeg[:100]}")
                self._send(ts=ts.timestamp(), jpeg=jpeg, frame_count=frame_count)
            except Exception as e:
                logger.error(f"----_on_frame: {e}")
                
                
    def _recording(self):
        logger.info(f"Scanner {self.group}: start recorder")
        while not self.stop_event.is_set():
            try:
                (uuid, ts, frame, metrics, frame_count) = self.record_queue.get()
                
                
                labels = dict(fps=self.video_fps, session=self.data.session, detected="1" if metrics.get("detected") else "0")
                
                if metrics.get("detected"):
                    labels.update({
                        "cx"          : str(metrics["cx"]),
                        "cy"          : str(metrics["cy"]),
                        "area_px"     : str(metrics["area_px"]),
                        "speed_px_s"  : str(metrics["speed_px_s"]),
                        "axial_pos"   : str(metrics["axial_pos"]),
                        "axial_speed" : str(metrics["axial_speed"]),
                    })    
                                
                self.recordDB.write(uuid, frame, labels, ts=ts)
                self.record_queue.task_done()
            except Exception as e:
                logger.error(f'recorder: {e}')


    def _init_grbl(self, feed=1000):
        logger.info(f"==== GRBLController try to start connection!")
        self.grbl.start_connection()
        self._send(state='serial', msg=f"Connected {self.grbl.port}")        
        
        self.grbl.go_origin(feed=feed)
        self.grbl.wait_for(2.0)


    def _listen_to_redis(self):
        try:
            logger.info(f"==== Scanner {self.group}: listen via redisDB")
            pubsub = redisDB.pubsub()
            pubsub.subscribe(self.group)
            #self._init_grbl()
            self.manager = MultiWellManager(process=self)
            self.manager.set_calib_debug(False)
            
            for message in pubsub.listen():
                try:
                    #logger.info(f"{message}")
                    if self.stop_event.is_set():
                        break

                    cmd = json.loads(str(message.get('data')))
                    logger.info(f"{cmd}")

                    if not isinstance(cmd, dict):
                        continue

                    self._send(state=cmd["type"], msg=f"Cmd: {cmd.get('topic')} {cmd.get('value', '')}")                   
                    if cmd["type"]=="scanner":
                        topic = cmd.get("topic")
                        if topic == 'init':
                            self.cam.set_circular_crop(self.crop)
                            self.cam._active_median = False
                            self.grbl.go_origin(feed=self.manager.feed)

                        elif topic == 'scan' or topic == 'simulate':                           
                            logger.info(f"==== Scan {cmd}")
                            sid = cmd.get("session", '0')
                            if sid == "0":
                                self._send(state='error', msg=str(_('La session est nulle!...')))
                            else:
                                self.cam._active_median = False
                                self.manager.scanning(sid, simulate=(topic=='simulate'))
                                self._send(state=topic, msg=str(_('Balayage démarré...')))
                                
                    elif cmd["type"]=="calibrate":
                        topic = cmd.get("topic")
                        value = cmd.get("value")
                        buttons = None
                        if topic == 'init':                           
                            self.manager.set_default_values(
                                feed=int(cmd.get("feed")), 
                                step=float(cmd.get("step")), 
                                duration=float(cmd.get("duration"))
                            )
                            position = cmd.get("position")
                            self.manager.set_multiwell(position)
                            self.cam.set_circular_crop(None)
                            self.cam._active_median = False                          
                            buttons = self.manager.multiwell_buttons()

                        elif topic == 'up':
                            self.grbl.move_relative(dy=self.manager.step, feed=self.manager.feed)
                            
                        elif topic == 'down':
                            self.grbl.move_relative(dy=-self.manager.step, feed=self.manager.feed)
                            
                        elif topic == 'right':
                            self.grbl.move_relative(dx=self.manager.step, feed=self.manager.feed)
                            
                        elif topic == 'left':
                            self.grbl.move_relative(dx=-self.manager.step, feed=self.manager.feed)
                            
                        elif topic == 'median':
                            self.cam._active_median = not self.cam._active_median
                            continue
                        
                        elif topic == 'crop':
                            self.cam._active_crop = not self.cam._active_crop
                            self.cam.set_circular_crop(self.crop) if self.cam._active_crop else self.cam.set_circular_crop(None)
                            continue
                        
                        elif topic == 'crop_radius':
                            self.conf.calibration_crop_radius=int(value)
                            self.crop = self.set_crop_radius(self.conf.calibration_crop_radius)
                            self.conf.save()
                            self.cam.set_circular_crop(self.crop)
                            continue   
                                             
                        elif topic == 'position':
                            self.manager.set_multiwell(value)
                            buttons = self.manager.multiwell_buttons()
                            
                        elif topic == 'step':
                            self.manager.step = float(value)
                            
                        elif topic == 'feed':
                            self.manager.feed = int(value)
                            
                        elif topic == 'duration':
                            self.manager.duration = float(value)   
                                 
                        elif topic == 'goto_0':
                            self.grbl.go_origin(feed=self.manager.feed)
                            self.manager.well_iterator.reset()
                            
                        elif topic == 'goto_xy':
                            self.grbl.move_to(self.manager.xbase, self.manager.ybase, feed=self.manager.feed)
                            self.manager.well_iterator.seek(0)
                            
                        elif topic == 'xy_base':
                            self.manager.set_position()
                            
                        elif topic == 'test':
                            self.manager.scan_test()
                            continue
                        
                        elif topic == 'auto':
                            self.manager.set_calib_debug(True)
                            self.cam.set_circular_crop(self.crop)
                            self.manager.scan_test(auto=True)
                            continue
                           
                        elif topic == 'center':
                            dx_mm = self.cam.align_detection["offset_x_mm"]
                            dy_mm = self.cam.align_detection["offset_y_mm"]
                            self.manager.px_per_mm = self.cam.align_detection["px_per_mm"]
                            self.grbl.move_to(self.grbl.x + dx_mm, self.grbl.y + dy_mm, feed=150)
                            self._send(state='center', msg=self.cam.align_detection["msg"])  
                            continue
                        
                        elif topic == 'halt':
                            self.manager.halt_scanning()
                            
                        
                        elif topic == 'calib_debug':
                            msg = self.manager.calib_toggle_debug()
                            self._send(**msg)    
                            continue
                        
                        elif topic == 'previous':
                            msg = self.manager.previous_well()
                            self._send(**msg)  
   
                        elif topic == 'next':
                            msg = self.manager.next_well()
                            self._send(**msg)  

                        elif topic == 'goto':
                            msg = self.manager.goto_well(int(value))
                            self._send(**msg)
               
                        elif topic == 'set_well':
                            msg = self.manager.set_well_position()
                            self._send(**msg)
                 
                        self._send(
                            xbase=self.manager.xbase, 
                            ybase=self.manager.ybase, 
                            x=self.grbl.x, 
                            y=self.grbl.y, 
                            xy=True, 
                            dxy=True, 
                            dx=self.manager.dx, 
                            dy=self.manager.dy,
                            buttons=buttons,
                            current=self.manager.get_well_order(),
                        )
                except Exception as e:
                    logger.error(f'scanner listen_to_redis: {e}')
        finally:
            pubsub.unsubscribe()
            pubsub.close()


#=================================================================
#
#    REPLAY Buffer glissant
#
#    temps réel replay →
#    |---- préchargé ----|---- en lecture ----|---- à venir ----|
#            -2s                  t                  +3s
#    max_seconds:
#        3s → faible latence, faible RAM
#        10s → seek ultra fluide
#=================================================================

class ReplayBuffer:
    def __init__(self, max_seconds=5.0):
        self.max_seconds = max_seconds
        self.frames = {}          # ts → bytes
        self.timestamps = []      # triée
        self.lock = Lock()

    def push(self, ts, frame):
        with self.lock:
            if ts in self.frames:
                return
            bisect.insort(self.timestamps, ts)
            self.frames[ts] = frame
            self._cleanup(ts)

    def get_nearest(self, ts_us: int):
        try:
            with self.lock:
                if not self.timestamps:
                    return None
                idx = bisect.bisect_right(self.timestamps, ts_us) - 1
                if idx < 0:
                    idx = 0
                nearest_ts = self.timestamps[idx]
                return nearest_ts, self.frames[nearest_ts]
        except Exception as e:  # @UnusedVariable
            pass
            #logger.error(f"{e}")
        return None

    def clear(self):
        with self.lock:
            self.frames.clear()
            self.timestamps.clear()


    def _cleanup(self, current_ts):
        # supprime les frames trop anciennes
        limit = current_ts - self.max_seconds
        while self.timestamps and self.timestamps[0] < limit:
            ts = self.timestamps.pop(0)
            del self.frames[ts]


class ReplayClock:
    def __init__(self, uuid, start_ts, stop_ts, fps=5.0, speed=1.0):
        self.uuid = uuid
        self.start_ts = start_ts
        self.stop_ts = stop_ts
        self.ts = start_ts
        self.fps = fps
        self.speed = speed
        self.paused = False
        self._seek_ts = None
        self._last_tick = time.monotonic()
        self.lock = Lock()
        self.delta = self.stop_ts - self.start_ts

    def tick(self):
        with self.lock:
            now = time.monotonic()
            dt_sec = now - self._last_tick
            self._last_tick = now
            delta_us = int(dt_sec * 1_000_000 * self.speed)
            self.ts += delta_us
            if self.ts >= self.stop_ts:
                self.paused = True
                return None
            return self.ts

    def sleep_duration(self) -> float:
        with self.lock:
            frame_us = int(1_000_000 / self.fps)
            return max((frame_us / self.speed) / 1_000_000, 0.001)

    def play(self):
        with self.lock:
            self.paused = False

    def pause(self):
        with self.lock:
            self.paused = True

    def stop(self):
        with self.lock:
            self.paused = True
            self.ts = self.start_ts
            return self.ts

    def set_speed(self, speed):
        with self.lock:
            self.speed = max(0.1, speed)

    def seek(self, k):
        with self.lock:
            self._seek_ts = int( self.start_ts + (k * self.delta) )

    def consume_seek(self):
        with self.lock:
            ts = self._seek_ts
            self._seek_ts = None
            return ts
        return None

    def progress(self, ts: int) -> float:
        ptx =  (ts - self.start_ts) / self.delta
        return round( max(0.0, min(1.0, ptx)), 6)


class ReplayProcess(Task):

    def __init__(self, latency=5.0):
        super().__init__()
        self.channel_layer = get_channel_layer()
        self.latency = latency
        self.group = f'replay_proc'
        self.recordDB = cameraDB
        self.stop_event = Event()
        self.clock = None
        self.query = None
        self.running = asyncio.Event()


    def __call__(self, uuid, *args, **kwargs):
        return self.start(*args, **kwargs)


    def start(self, *args, **kwargs):
        try:
            self.stop_event.clear()
            Thread(target=self._listen_to_redis, daemon=True).start()
        except Exception as e:
            logger.error(f"Replay error: {e}")
            raise Ignore()

    def stop(self):
        self.stop_event.set()
        logger.info(f"==== ReplayProcess stopped.")

    def _listen_to_redis(self):
        try:
            loop = None
            logger.info(f"==== ReplayProcess {self.group}: listen via redisDB")
            pubsub = redisDB.pubsub()
            pubsub.subscribe(self.group)

            for message in pubsub.listen():
                try:
                    if self.stop_event.is_set():
                        break

                    cmd = json.loads(str(message.get('data')))
                    logger.info(f"{cmd}")

                    if not isinstance(cmd, dict):
                        continue

                    if cmd["type"] == "replay":
                        action = cmd["action"]
                        if action in ["init", "play"]:
                            uuid = cmd.get("uuid")
                            start_ts, stop_ts = int(cmd.get('dt_start')), int(cmd.get('dt_stop'))

                            fps, speed = float(cmd.get('fps', 5.0)), int(cmd.get('speed'))
                            self.clock = ReplayClock(uuid, start_ts, stop_ts, fps, speed)
                            if action == "init":
                                if loop:
                                    utils.stop_async(loop)
                                    loop = None
                            elif action == "play":
                                if not loop:
                                    loop = utils.start_async()
                                    utils.submit_async(loop, self._replay())
                                self.clock.play()

                        elif action == 'stop':
                            self.running.set()
                            if loop:
                                utils.stop_async(loop)
                            loop = None
                            ts = self.clock.stop()
                            async_to_sync(self._send_message)('video-reset', dt_start=ts, percent=0.0)

                        elif action == 'pause':
                            self.clock.pause()

                        elif action == 'speed':
                            self.clock.set_speed(cmd.get("value"))

                        elif action == 'seek':
                            k = float(cmd.get("value"))
                            self.clock.seek(k)

                except Exception as e:
                    logger.error(f'ReplayProcess::listen_to_redis: {e}')
        finally:
            self.running.set()
            utils.stop_async(loop)
            pubsub.unsubscribe()
            pubsub.close()

    async def _send(self, payload):
        await self.channel_layer.group_send(self.group, {"type": 'replay.message', "text": payload  })

    async def _send_message(self, motif,  **msg):
        payload = {
            'uuid': self.clock.uuid,
            'motif': motif,
            **msg
        }
        await self._send(payload)

    async def _send_frame(self,  ts, jpg_bytes):
        payload = {
            'uuid': self.clock.uuid,
            "ts": ts,
            "progress": self.clock.progress(ts),
            "jpeg": base64.b64encode(jpg_bytes).decode()
        }
        await self._send(payload)

    def _create_query(self, clock):
        return self.recordDB.query(clock.uuid, start=clock.ts, stop=clock.stop_ts )

    async def _replay(self):
        try:
            self.running.clear()
            query = self._create_query(self.clock)
            self.buffer = ReplayBuffer(max_seconds=self.latency)
            while not self.running.is_set():
                try:
                    # ---- seek ? ----
                    seek_ts = self.clock.consume_seek()
                    if seek_ts is not None:
                        self.clock.ts = seek_ts
                        query = self._create_query(self.clock)
                        await asyncio.sleep(0.01)
                        continue

                    # ---- pause ----
                    if self.clock.paused:
                        await asyncio.sleep(0.5)
                        continue

                    # ---- frame ----
                    record = await anext(query)
                    frame = await record.read_all()

                    self.buffer.push(record.timestamp, frame)
                    if record.timestamp < self.clock.ts + self.buffer.max_seconds:
                        continue

                    # ---- get frame ----
                    nearest = self.buffer.get_nearest(self.clock.ts)
                    if nearest is None:
                        await asyncio.sleep(0.01)
                        continue

                    # ---- emit jpg ----
                    frame_ts, jpg = nearest
                    await self._send_frame(frame_ts, jpg)

                    # ---- avance temps ----
                    self.clock.tick()
                    await asyncio.sleep(self.clock.sleep_duration())

                except StopAsyncIteration:
                    self.clock.pause()
                    self.buffer.clear()

                except Exception as e:
                    logger.error(f'_replay loop: {e}')

                    await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"_replay: {e}")
