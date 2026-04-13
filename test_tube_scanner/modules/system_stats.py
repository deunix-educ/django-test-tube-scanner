'''
Created on 3 févr. 2026

@author: denis
'''
from django.conf import settings

# myapp/system_stats.py
import threading
import time
import os
import psutil

# intervale de mise à jour (secondes)
REFRESH_INTERVAL = 5
RAMDISK = "/mnt/ramdisk"

_cache = {
    "shm": [],
    "cpu_info": {},
    "memory_info": {},
    "disk_info": {},
    "ramdisk_info": {},
    "updated_at": None
}

_lock = threading.Lock()
_timer = None


def _collect_once():
    data = {}

    # shm: liste /dev/shm si disponible
    try:
        path = "/dev/shm"
        data["shm"] = os.listdir(path) if os.path.exists(path) and os.path.isdir(path) else []
    except Exception as e:
        data["shm_error"] = str(e)


    # cpu_info
    try:
        cpu_times = psutil.cpu_times_percent(interval=None, percpu=False)._asdict()
        data["cpu_info"] = {
            "cpu_count": psutil.cpu_count(logical=True),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_times_percent": cpu_times
        }
    except Exception as e:
        data["cpu_info_error"] = str(e)


    # memory_info
    try:
        vm = psutil.virtual_memory()._asdict()
        sm = psutil.swap_memory()._asdict()
        data["memory_info"] = {"virtual_memory": vm, "swap_memory": sm}
    except Exception as e:
        data["memory_info_error"] = str(e)


    # disk_info (root and partitions)
    # ex: if mountpoint == "/ramdisk" and fstype=="tmpfs" then usage.percent, usage.free, etc ...
    try:
        usage_root = psutil.disk_usage("/")._asdict()
        parts = []
        for p in psutil.disk_partitions(all=False):
            try:
                du = psutil.disk_usage(p.mountpoint)._asdict()
            except Exception:
                du = {}
            parts.append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "usage": du})
        data["disk_info"] = {"root": usage_root, "partitions": parts}
    except Exception as e:
        data["disk_info_error"] = str(e)

    # ramdisk
    # ex: if mountpoint == "/ramdisk" and fstype=="tmpfs" then usage.percent, usage.free, etc ...
    try:
        for part in psutil.disk_partitions(all=True):
            if part.mountpoint == RAMDISK and part.fstype.lower() == "tmpfs":
                usage = psutil.disk_usage(part.mountpoint)
                data["ramdisk_info"] = {
                    "percent": usage.percent,
                    "mount": part.mountpoint,
                    "device": part.device,
                    "fstype": part.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                }
    except Exception as e:
        data["ramdisk_info_error"] = str(e)

    data["updated_at"] = time.time()
    return data


def _update_cache():
    global _timer
    try:
        new = _collect_once()
        with _lock:
            _cache.update(new)
    finally:
        # reprogrammer
        _timer = threading.Timer(REFRESH_INTERVAL, _update_cache)
        _timer.daemon = True
        _timer.start()


def start_background_updater(interval_seconds: int = None):
    global REFRESH_INTERVAL, _timer
    if interval_seconds:
        REFRESH_INTERVAL = interval_seconds
    if _timer is not None:
        return
    # première collecte synchronisée
    with _lock:
        _cache.update(_collect_once())
    _timer = threading.Timer(REFRESH_INTERVAL, _update_cache)
    _timer.daemon = True
    _timer.start()


def stop_background_updater():
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None


def get_cached_stats():
    with _lock:
        # retourner copie pour sécurité
        return dict(_cache)
