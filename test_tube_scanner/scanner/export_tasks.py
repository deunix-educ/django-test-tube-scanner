# Tâches d'exportation pour les vidéos de caméra
import zipfile
from celery.utils.log import get_task_logger
import shutil
import os, sys
import posix_ipc
import mmap
import cv2
import numpy as np
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from reduct.time import unix_timestamp_to_iso

from .process import CameraRecordManager, cameraDB

logger = get_task_logger(__name__)

def progress_bar(iteration, total, prefix='', suffix='', length=30, fill='█'):
    percent = ("{0:.1f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    sys.stdout.write(f'\r{prefix} |{bar}| {percent}% {suffix}')
    sys.stdout.flush()
    

def delete_file_later(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        logger.error(f"[cleanup] error deleting {path}: {e}")
        raise


async def remove_video_by_uuid(uuid, start_ts=None, end_ts=None, when=None):
    record_manager = CameraRecordManager(cameraDB)
    await record_manager.remove(uuid, start_ts, end_ts)


async def remove_video(uuid, start_ts, end_ts, when=None):
    try:
        await remove_video_by_uuid(uuid, start_ts, end_ts, when=when)
        return JsonResponse({'state': 'ok'}, status=200)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


async def shm_download_video(uuid, start_ts, end_ts, frame_rate=5, opencv_fourcc_format='mp4v', opencv_video_type='mp4'):
    try:
        record_manager = CameraRecordManager(cameraDB)
        total_size = await record_manager.size(uuid, start_ts, end_ts)

        # segment de mémoire partagée pour stocker les frames
        shm_size = int(total_size * 1.5)
        shm_name = f"/video_frames_{uuid}"
        try:
            shm = posix_ipc.SharedMemory(shm_name, posix_ipc.O_CREAT | posix_ipc.O_EXCL, size=shm_size)
        except posix_ipc.ExistentialError:
            existing = posix_ipc.SharedMemory(shm_name, flags=0)
            existing.close_fd()
            try:
                existing.unlink()
            except posix_ipc.ExistentialError:
                pass
            shm = posix_ipc.SharedMemory(shm_name, posix_ipc.O_CREAT | posix_ipc.O_EXCL, size=shm_size)
        mm = mmap.mmap(shm.fd, shm_size)

        queries = record_manager.query(uuid, start_ts, end_ts)
        offset = 0
        frame_sizes = []
        total = 0
        async for record in queries:
            frame_bytes = await record.read_all()
            frame_size = len(frame_bytes)

            mm[offset:offset + frame_size] = frame_bytes
            frame_sizes.append(frame_size)
            offset += frame_size
            total += 1

        if not frame_sizes:
            return JsonResponse({'error': 'Aucune frame trouvée'}, status=404)

        video_path = os.path.join(settings.MEDIA_ROOT, f"output.{opencv_video_type}")
        fourcc = cv2.VideoWriter_fourcc(* opencv_fourcc_format)

        # Lit les frames depuis la mémoire partagée
        current_offset = 0
        i = 0
        for size in frame_sizes:
            frame_bytes = mm[current_offset:current_offset + size]
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if 'video' not in locals():
                height, width, _ = frame.shape
                video = cv2.VideoWriter(video_path, fourcc, frame_rate, (width, height))
            video.write(frame)
            current_offset += size
            
            progress_bar(i + 1, total, prefix=f'Progression {uuid}:', suffix='Terminé', length=30)
            i+=1             
            
        video.release()

        # Nettoie la mémoire partagée
        shm.unlink()

        # Vérifier que le fichier existe
        if not os.path.exists(video_path):
            logger.error(f"Fichier non créé: {video_path}")
            return JsonResponse({'error': 'Erreur création vidéo'}, status=500)

        # Lit le fichier vidéo généré
        with open(video_path, 'rb') as f:
            video_bytes = f.read()

        # Retourne la vidéo en réponse
        response = HttpResponse(video_bytes, content_type='video/mp4')
        response['Content-Disposition'] = f'attachment; filename="{video_path}"'
        response['Content-Length'] = os.path.getsize(video_path)


        # Supprime le fichier temporaire
        os.remove(video_path)
        return response

    except Exception as e:
        logger.error(f"shm_download_video: {e}")
        return JsonResponse({'error': str(e)}, status=500)

# ─────────────────────────────────────────────
##
# ─────────────────────────────────────────────
def remote_mount_available(mount_point: str = "/mnt/exports_cam") -> bool:
    """
    Vérifie que le point de montage Samba est actif et accessible en écriture.
    """
    return os.path.ismount(mount_point) and os.access(mount_point, os.W_OK)


def _copy_to_destinations(source_path: str, filename: str) -> dict:
    """
    Copie le fichier exporté vers les destinations configurées.
    Retourne un dict avec les chemins effectivement écrits.
    """
    results = {"local": None, "remote": None}

    for dest in settings.EXPORT_DESTINATIONS:

        if dest == "local":
            # Déjà sur place, rien à copier
            results["local"] = source_path

        elif dest == "remote":
            remote_path = os.path.join(settings.EXPORT_REMOTE_DIR, filename)
            try:
                if not remote_mount_available(settings.EXPORT_REMOTE_DIR):
                    logger.warning("Partage Samba non disponible, copie ignorée")
                    results["remote_error"] = "Montage indisponible"
                    continue                
                
                # Copie locale vers le point de montage Samba
                shutil.copy2(source_path, remote_path)
                results["remote"] = remote_path
                logger.info("Copie distante OK : %s", remote_path)
            except OSError as exc:
                # Le partage est peut-être absent (machine Windows éteinte)
                logger.error("Copie distante échouée [%s] : %s", remote_path, exc)
                results["remote_error"] = str(exc)

    return results


# ─────────────────────────────────────────────
# Tâche 1 : Export des frames en ZIP d'images
# ─────────────────────────────────────────────
async def export_images_zip(
    uuid: str,
    start_ts: float | None = None,
    end_ts: float | None = None,
    jpeg_quality: int = 85,
    max_zip_size_mb: int = 0,
    max_image_width: int = 0,
    max_image_height: int = 0,
):
    """
    Exporte les frames d'une caméra sous forme d'archive ZIP contenant des JPEG.

    :param uuid: Identifiant de la caméra
    :param start_ts: Timestamp de début (epoch secondes)
    :param end_ts: Timestamp de fin (epoch secondes)
    :param max_zip_size_mb: Taille maximale du ZIP en Mo (0 = illimité)
    :param jpeg_quality: Qualité JPEG 1-100 (défaut 85)
    :param max_image_width: Redimensionnement max largeur en px (0 = non redimensionné)
    :param max_image_height: Redimensionnement max hauteur en px (0 = non redimensionné)
    :return: Chemin du fichier ZIP généré + rapport JSON
    """
    shm = None
    mm = None
    shm_name = f"/img_frames_{uuid}"

    try:
        # --- Chargement des frames en mémoire partagée ---
        record_manager = CameraRecordManager(cameraDB)
        total_size = await record_manager.size(uuid, start_ts, end_ts)
        shm_size = int(total_size * 1.5)

        try:
            shm = posix_ipc.SharedMemory(
                shm_name, posix_ipc.O_CREAT | posix_ipc.O_EXCL, size=shm_size
            )
        except posix_ipc.ExistentialError:
            existing = posix_ipc.SharedMemory(shm_name, flags=0)
            existing.close_fd()
            try:
                existing.unlink()
            except posix_ipc.ExistentialError:
                pass
            shm = posix_ipc.SharedMemory(
                shm_name, posix_ipc.O_CREAT | posix_ipc.O_EXCL, size=shm_size
            )

        mm = mmap.mmap(shm.fd, shm_size)

        queries = record_manager.query(uuid, start_ts, end_ts)
        if not start_ts:
            start_ts = record_manager.oldest_ts
        if not end_ts:
            end_ts = record_manager.latest_ts

        offset = 0
        frame_sizes = []
        ts = []
        total = 0
        async for record in queries:
            ts.append(record.timestamp)
            frame_bytes = await record.read_all()
            frame_size = len(frame_bytes)

            mm[offset:offset + frame_size] = frame_bytes
            frame_sizes.append(frame_size)
            offset += frame_size
            total += 1

        if not frame_sizes:
            return {"status": "error", "message": "Aucune frame trouvée"}

        # --- Génération du ZIP ---
        max_zip_bytes = max_zip_size_mb * 1024 * 1024 if max_zip_size_mb > 0 else 0
        ts_s = unix_timestamp_to_iso(start_ts)
        zip_filename = f"{uuid}_{ts_s}.zip"
        zip_path = os.path.join(settings.EXPORTS_LOCAL_PATH, 'images', zip_filename)
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)

        skipped = 0
        written = 0
        current_offset = 0
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]

        i = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, size in enumerate(frame_sizes):
                # Vérification de la taille du ZIP
                if max_zip_bytes and os.path.getsize(zip_path) >= max_zip_bytes:
                    skipped += len(frame_sizes) - idx
                    logger.warning(
                        "export_images_zip: limite %d Mo atteinte, %d frames ignorées",
                        max_zip_size_mb,
                        len(frame_sizes) - idx,
                    )
                    break

                frame_bytes = mm[current_offset:current_offset + size]
                nparr = np.frombuffer(frame_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if frame is None:
                    current_offset += size
                    skipped += 1
                    continue

                # Redimensionnement optionnel
                if max_image_width > 0 or max_image_height > 0:
                    frame = _resize_frame(frame, max_image_width, max_image_height)

                # Encodage JPEG en mémoire puis ajout au ZIP
                ok, buf = cv2.imencode(".jpg", frame, encode_params)
                if ok:
                    #zf.writestr(f"frame_{idx:06d}.jpg", buf.tobytes())
                    ts_iso = unix_timestamp_to_iso(ts[idx])
                    #logger.info(f"export_images_zip: adding frame {idx} with timestamp {ts_iso} to ZIP")
                    zf.writestr(f"{uuid}_{ts_iso}.jpg", buf.tobytes())
                    written += 1
                    
                progress_bar(i + 1, total, prefix=f'Progression {uuid}:', suffix='Terminé', length=30)
                i+=1                   
                current_offset += size
        
        ## Copie vers les destinations (local + Samba)    
        #destinations = _copy_to_destinations(zip_path, zip_filename)   
        return {
            "status": "success",
            "zip_path": zip_path,
            "frames_written": written,
            "frames_skipped": skipped,
            "jpeg_quality": jpeg_quality,
            #"destinations": destinations,
        }

    except Exception as exc:
        logger.error("export_images_zip [%s]: %s", uuid, exc, exc_info=True)
        return {"status": "error", "message": str(exc)}

    finally:
        if mm:
            mm.close()
        if shm:
            try:
                shm.unlink()
            except posix_ipc.ExistentialError:
                pass


# ─────────────────────────────────────────────
# Tâche 2 : Export des frames en vidéo MP4
# ─────────────────────────────────────────────
#@shared_task(bind=True)
async def export_video_mp4(
    uuid: str,
    start_ts: float | None = None,
    end_ts: float | None = None,
    frame_rate: int = 5,
    opencv_fourcc_format='mp4v',
    opencv_video_type='mp4',
    max_video_size_mb: int = 0,
    max_width: int = 0,
    max_height: int = 0,
):
    """
    Exporte les frames d'une caméra en fichier MP4 via OpenCV.

    :param uuid: Identifiant de la caméra
    :param start_ts: Timestamp de début (epoch secondes)
    :param end_ts: Timestamp de fin (epoch secondes)
    :param frame_rate: Images par seconde (défaut 5)
    :param max_video_size_mb: Taille maximale du MP4 en Mo (0 = illimité)
    :param max_width: Redimensionnement max largeur en px (0 = non redimensionné)
    :param max_height: Redimensionnement max hauteur en px (0 = non redimensionné)
    :return: Chemin du fichier MP4 généré + rapport JSON
    """
    shm = None
    mm = None
    video = None
    shm_name = f"/vid_frames_{uuid}"

    try:      
        # --- Chargement des frames en mémoire partagée ---
        record_manager = CameraRecordManager(cameraDB)
        total_size = await record_manager.size(uuid, start_ts, end_ts)
        shm_size = int(total_size * 1.5)

        try:
            shm = posix_ipc.SharedMemory(
                shm_name, posix_ipc.O_CREAT | posix_ipc.O_EXCL, size=shm_size
            )
        except posix_ipc.ExistentialError:
            existing = posix_ipc.SharedMemory(shm_name, flags=0)
            existing.close_fd()
            try:
                existing.unlink()
            except posix_ipc.ExistentialError:
                pass
            shm = posix_ipc.SharedMemory(
                shm_name, posix_ipc.O_CREAT | posix_ipc.O_EXCL, size=shm_size
            )

        mm = mmap.mmap(shm.fd, shm_size)
        queries = record_manager.query(uuid, start_ts, end_ts)
        
        if not start_ts:
            start_ts = record_manager.oldest_ts
        if not end_ts:
            end_ts = record_manager.latest_ts        
    
        offset = 0
        frame_sizes = []
        total = 0
        async for record in queries:
            frame_bytes = await record.read_all()
            frame_size = len(frame_bytes)

            mm[offset:offset + frame_size] = frame_bytes
            frame_sizes.append(frame_size)
            offset += frame_size
            total +=1

        if not frame_sizes:
            return {"status": "error", "message": "Aucune frame trouvée"}


        # --- Génération du MP4 ---
        max_video_bytes = max_video_size_mb * 1024 * 1024 if max_video_size_mb > 0 else 0
        
        ts_s = unix_timestamp_to_iso(start_ts)
        video_path = os.path.join(
            settings.EXPORTS_LOCAL_PATH, 'videos', f"{uuid}_{ts_s}.{opencv_video_type}"
        )
        os.makedirs(os.path.dirname(video_path), exist_ok=True)

        fourcc = cv2.VideoWriter_fourcc(*opencv_fourcc_format)
        skipped = 0
        written = 0
        current_offset = 0

        i=0
        for idx, size in enumerate(frame_sizes):
            # Vérification de la taille du MP4 en cours
            if (
                max_video_bytes
                and video is not None
                and os.path.exists(video_path)
                and os.path.getsize(video_path) >= max_video_bytes
            ):
                skipped += len(frame_sizes) - idx
                logger.warning(
                    "export_video_mp4: limite %d Mo atteinte, %d frames ignorées",
                    max_video_size_mb,
                    len(frame_sizes) - idx,
                )
                break

            frame_bytes = mm[current_offset:current_offset + size]
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                current_offset += size
                skipped += 1
                continue

            # Redimensionnement optionnel
            if max_width > 0 or max_height > 0:
                frame = _resize_frame(frame, max_width, max_height)

            # Initialisation du VideoWriter sur la première frame valide
            if video is None:
                h, w, _ = frame.shape
                video = cv2.VideoWriter(video_path, fourcc, frame_rate, (w, h))

            video.write(frame)
            written += 1
            current_offset += size

            progress_bar(i + 1, total, prefix=f'Progression {uuid}:', suffix='Terminé', length=30)
            i+=1

        if video:
            video.release()

        if not os.path.exists(video_path):
            return {"status": "error", "message": f"Fichier {opencv_video_type} non créé"}
        
        ## Copie vers les destinations (local + Samba)
        #filename = os.path.basename(video_path)
        #destinations = _copy_to_destinations(video_path, filename)
        return {
            "status": "success",
            "video_path": video_path,
            "frames_written": written,
            "frames_skipped": skipped,
            "frame_rate": frame_rate,
            "file_size_mb": round(os.path.getsize(video_path) / 1024 / 1024, 2),
            #"destinations": destinations,
        }

    except Exception as exc:
        logger.error("export_video_mp4 [%s]: %s", uuid, exc, exc_info=True)
        return {"status": "error", "message": str(exc)}

    finally:
        if mm:
            mm.close()
        if shm:
            try:
                shm.unlink()
            except posix_ipc.ExistentialError:
                pass


# ─────────────────────────────────────────────
# Utilitaire commun
# ─────────────────────────────────────────────
def _resize_frame(
    frame: np.ndarray, max_width: int, max_height: int
) -> np.ndarray:
    """
    Redimensionne une frame en conservant le ratio si un max est dépassé.
    max_width ou max_height à 0 signifie sans contrainte sur cet axe.
    """
    h, w = frame.shape[:2]
    scale = 1.0

    if max_width > 0 and w > max_width:
        scale = min(scale, max_width / w)
    if max_height > 0 and h > max_height:
        scale = min(scale, max_height / h)

    if scale < 1.0:
        new_w = int(w * scale)
        new_h = int(h * scale)
        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

    return frame

# tasks/export_tasks.py

from celery import shared_task, group
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_session_exports(self, session_id: str):
    """
    Point d'entrée déclenché par django_celery_beat.
    Lance en parallèle l'export images et l'export vidéo de la session.
    """
    from cameras.models import ExportSession

    try:
        session = ExportSession.objects.get(session_id=session_id)
    except ExportSession.DoesNotExist:
        logger.error("run_session_exports: session %s introuvable", session_id)
        return {"status": "error", "message": "Session introuvable"}

    session.status = ExportSession.Status.RUNNING
    session.save(update_fields=["status"])

    try:
        # Lancement en parallèle avec group Celery
        job = group(
            export_all_images.s(session_id),
            export_all_videos.s(session_id),
        ).apply_async()

        results = job.get(timeout=7200)         # 2h max pour les deux

        session.status      = ExportSession.Status.DONE
        session.exported_at = timezone.now()
        session.save(update_fields=["status", "exported_at"])

        return {"status": "success", "results": results}

    except Exception as exc:
        session.status = ExportSession.Status.ERROR
        session.save(update_fields=["status"])
        logger.error("run_session_exports [%s]: %s", session_id, exc, exc_info=True)
        return {"status": "error", "message": str(exc)}


@shared_task(bind=True)
def export_all_images(self, session_id: str):
    """
    Export ZIP de toutes les images de la session.
    """
    from cameras.models import ExportSession

    session = ExportSession.objects.get(session_id=session_id)

    return export_images_zip(
        session.camera_uuid,
        session.start_ts,
        session.end_ts,
        max_zip_size_mb  = session.max_zip_size_mb,
        jpeg_quality     = session.jpeg_quality,
        max_image_width  = session.max_image_width,
        max_image_height = session.max_image_height,
    )


@shared_task(bind=True)
def export_all_videos(self, session_id: str):
    """
    Export MP4 de toutes les vidéos de la session.
    """
    from cameras.models import ExportSession

    session = ExportSession.objects.get(session_id=session_id)

    return export_video_mp4(
        session.camera_uuid,
        session.start_ts,
        session.end_ts,
        frame_rate        = session.frame_rate,
        max_video_size_mb = session.max_video_size_mb,
        max_width         = session.max_width,
        max_height        = session.max_height,
    )




