'''
Created on 20 avr. 2022

@author: denis
'''
import yaml
import time
import importlib
from datetime import datetime
import string, secrets
import uuid
from threading import Event, Thread
from urllib.parse import urlsplit
import asyncio
# sysutils.py
import os
import mmap
import fcntl
import psutil


SHM_DIR = "/dev/shm"


def open_shm(name: str, size: int, create=True):
    path = os.path.join(SHM_DIR, name)
    flags = os.O_RDWR | (os.O_CREAT if create else 0)
    fd = os.open(path, flags)
    try:
        if create:
            os.ftruncate(fd, size)
        mm = mmap.mmap(fd, size)
    finally:
        os.close(fd)
    return mm, path


def read_shm(name: str, size: int):
    mm, path = open_shm(name, size, create=False)  # @UnusedVariable
    try:
        mm.seek(0)
        data = mm.read(size)
        return data.rstrip(b"\0")
    finally:
        mm.close()


def write_shm(name: str, size: int, data: bytes):
    mm, path = open_shm(name, size, create=True)
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            mm.seek(0)
            mm.write(data.ljust(size, b"\0")[:size])
            mm.flush()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        mm.close()
        os.close(fd)


def get_tmpfs_info(mount_point="/ramdisk"):
    def sizeof(n):
        for unit in ['B','KB','MB','GB','TB']:
            if n < 1024:
                return f"{n:.1f}{unit}"
            n /= 1024
        return f"{n:.1f}PB"

    usage = None
    for part in psutil.disk_partitions(all=True):
        if part.mountpoint == mount_point and part.fstype.lower() == "tmpfs":
            usage = psutil.disk_usage(part.mountpoint)
            print(f"Mount: {part.mountpoint}")
            print(f"  Device: {part.device}")
            print(f"  Fstype: {part.fstype}")
            print(f"  Total: {usage.total} bytes ({sizeof(usage.total)})")
            print(f"  Used:  {usage.used} bytes ({sizeof(usage.used)})")
            print(f"  Free:  {usage.free} bytes ({sizeof(usage.free)})")
            print(f"  Percent used: {usage.percent}%")
            break
    return {
        "percent": usage.percent,
        "mount": part.mountpoint,
        "device": part.device,
        "fstype": part.fstype,
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
    }


def get_cpu_info():
    # cpu percent par coeur et moyennes load
    return {
        "cpu_percent_per_cpu": psutil.cpu_percent(interval=0.5, percpu=True),
        "cpu_percent_total": psutil.cpu_percent(interval=None),
        "load_avg": os.getloadavg(),  # (1,5,15)
        "cpu_count": psutil.cpu_count(logical=True),
    }


def get_memory_info():
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    return {
        "total": vm.total,
        "available": vm.available,
        "used": vm.used,
        "free": vm.free,
        "percent": vm.percent,
        "swap_total": sm.total,
        "swap_used": sm.used,
        "swap_free": sm.free,
        "swap_percent": sm.percent,
    }


def get_disk_info(path="/"):
    du = psutil.disk_usage(path)
    return {
        "path": path,
        "total": du.total,
        "used": du.used,
        "free": du.free,
        "percent": du.percent,
    }


def extract_host_port_path(url, default_port=None):
    """
    Retoure (host, port, path) où:
    - host: string (IP ou hostname) ou None
    - port: int ou None (utilise default_port si fourni et aucun port explicite)
    - path: string (chemin + query + fragment si présents), ou '' si absent
    """
    parts = urlsplit(url if '://' in url else '//' + url, scheme='')
    host = parts.hostname
    port = parts.port or default_port
    # Reconstruire path complet: path + ('?' + query) + ('#' + fragment)
    path = parts.path or ''
    if parts.query:
        path += '?' + parts.query
    if parts.fragment:
        path += '#' + parts.fragment
    return host, port, path


def image_path(imagefile):
    image_path = imagefile.path
    pdir = os.path.dirname(image_path)
    os.makedirs(pdir, exist_ok=True)
    return str(image_path)


def serialize_datetime(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError("Type not serializable")


def start_async():
    loop = asyncio.new_event_loop()
    Thread(target=loop.run_forever, daemon=True).start()
    return loop


def stop_async(loop):
    loop.call_soon_threadsafe(loop.stop)


def submit_async(loop, awaitable):
    return asyncio.run_coroutine_threadsafe(awaitable, loop)


def to_choice(d):
    choices = []
    for k, v in d.items():
        choices.append((k, v))
    return choices


def get_instance_class(module):
    modulename, classname = module.rsplit(".", 1)
    return getattr(importlib.import_module(modulename), classname)


def wait_for(timeout):
    Event().wait(timeout)


def yaml_load(f):
    with open(f, 'r') as stream:
        return yaml.safe_load(stream)
    return {}


def yaml_save(f, context):
    with open(f, 'w') as stream:
        yaml.dump(context, stream, default_flow_style = False)


def get_uuid():
    return str(hex(uuid.getnode()))[2:]


def millis():
    return round(time.time() * 1000)


def now():
    return datetime.now()


def ts_now():
    # float second
    return now().timestamp()


def ts_now_s():
    return int(ts_now())


def ts_now_ms():
    return int(ts_now()*1000)


def ts_now_us():
    return int(ts_now()*1000000)


def random_num(n=16):
    alphabet = string.digits
    return ''.join(secrets.choice(alphabet) for i in range(n))  # @UnusedVariable


def random_chars(n=6):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for i in range(n))  # @UnusedVariable


def get_apikey(n=32):
    chars = 'abcdefgh01234ijklABCD4567EFGHIJKLmnopqrstuvwxyz0123456789MNOPQRS789TUVWXYZ'
    return ''.join(secrets.choice(chars) for i in range(n))  # @UnusedVariable


def gen_keywords(s):
    c = s.replace(',', ' ').replace('+', ' ')
    return [ w.strip() for w in c.split(' ') if w]


def gen_device_uuid(n=19):
    return hex(int(random_num(n)))[2:]


def get_device_uuid(n=19):
    return f'0x{gen_device_uuid(n)}'


