'''
Created on 28 avr. 2026

@author: denis
'''
from dataclasses import dataclass, asdict
from .models import Configuration

@dataclass
class DefaultConfig:
    """Constantes par défaut - utilisées en cas de problème BD"""
    sidebar_width: str = "25%"
    default_grid_columns: int = 3
    opencv_fourcc_format: str = 'mp4v'
    opencv_video_type: str = 'mp4'
    grbl_xmax: float = 350.0
    grbl_ymax: float = 250.0
    capture_type: str = 'rpi'
    webcam_device_index: int = 2
    image_quality: int = 90
    video_jpeg_quality: int = 90
    video_frame_rate: int = 5.0
    video_width_capture: int = 2028
    video_height_capture: int = 1520
    calibration_crop_radius: int = 500
    calibration_default_multiwell: str = 'HD'
    calibration_default_feed: int = 1000
    calibration_default_step: float = 1.0
    calibration_default_duration: float = 3.0
    tracking: bool = False 
    

class ScannerConstants:
    
    def __init__(self):
        self.conf = DefaultConfig()
        d = asdict(self.conf)
        v = d.keys()
        lst = Configuration.objects.filter(active=True).values(*v)
        if lst:
            values = lst[0]
            self.conf = DefaultConfig(**values)
            
    def get(self):
        return self.conf
    
    