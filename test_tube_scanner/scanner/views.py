#
from asgiref.sync import async_to_sync
import base64, json
from django.shortcuts import render
from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.conf import settings
from reduct.time import unix_timestamp_to_iso
from modules.system_stats import get_cached_stats, start_background_updater
from modules import reductstore

from .tasks import download_video, export_all_images, export_all_videos
from .process import CameraRecordManager, cameraDB
from . import models
from .constants import ScannerConstants

record_manager = CameraRecordManager(cameraDB)
start_background_updater()

    
@require_GET
def stats_view(request):
    """
    Retourne tout le cache (shm, cpu_info, memory_info, disk_info, updated_at)
    """
    try:
        data = get_cached_stats()
        return JsonResponse(data, safe=False)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

def global_context(request, **ctx):
    default_multiwell = models.MultiWell.objects.filter(default=True).first()
    conf = ScannerConstants().get()
    return dict(
        app_title=settings.APP_TITLE,
        app_sub_title=settings.APP_SUB_TITLE,
        domain_server=settings.DOMAIN_SERVER,
        conf=conf,
        default_position = default_multiwell.position or 'HD',
        export_destination=settings.EXPORT_DESTINATIONS,
        **ctx
    )

@login_required
def admin_view(request):
    return render(request, "scanner/iframe.html", context=global_context(request, link='/admin/'))

@login_required
def reductstore_view(request):
    return render(request, "scanner/redirection.html", context=global_context(request, link=f'http://{settings.DOMAIN_SERVER}:8383/'))

@login_required
def adminer_view(request):
    return render(request, "scanner/redirection.html", context=global_context(request, link=f'http://{settings.DOMAIN_SERVER}/adminer/'))

@login_required
def portainer_view(request):
    return render(request, "scanner/redirection.html", context=global_context(request, link=f'http://{settings.DOMAIN_SERVER}:9000/'))

@login_required
def supervisor_view(request):
    return render(request, "scanner/redirection.html", context=global_context(request, link=f'http://{settings.DOMAIN_SERVER}:9001/'))

@login_required
def supervisor_worker(request):
    return render(request, "scanner/redirection.html", context=global_context(request, link=f'http://{settings.DOMAIN_SERVER}:9001/logtail/test_tube:services'))

@login_required
def supervisor_scheduler(request):
    return render(request, "scanner/redirection.html", context=global_context(request, link=f'http://{settings.DOMAIN_SERVER}:9001/logtail/test_tube:planification'))

## Mainboard
@login_required
def scanning_view(request):
    ctx = dict(
        ws_route=settings.SCANNER_WEBSOCKET_ROUTE,
        columns=1,
        sessions=models.Session.objects.filter(active=True).all(),
        choice_title=_("Balayage multi-puits")
    )
    return render(request, "scanner/scanning.html", context=global_context(request, **ctx))

## Calibration
@login_required
def calibration_view(request):
    ctx = dict(
        ws_route=settings.SCANNER_WEBSOCKET_ROUTE,
        columns=1,
        choice_title=_("Calibration"),
        wells = models.MultiWell.objects.all(),
    )
    return render(request, "scanner/calibration.html", context=global_context(request, **ctx))


def get_not_active_experiments(session, expid=None):
    if session:
        experiments = models.SessionExperiment.experiment_by_session(session.id, active=False) or []
        if experiments and not expid:
            return experiments, experiments[0]
        for e in experiments:
            if expid == str(e.id):
                return experiments, e
    return [], None
    
    
## images
def get_images(uuid):
    oldest, latest, n, images = 0, 0, 0, []

    filters = record_manager.set_filters(test=False)
    queries = record_manager.query(uuid, filters=filters)
    while True:
        try:
            record, content = async_to_sync(record_manager.record_content)(queries)
            if n<1:
                oldest = record.timestamp
            latest = record.timestamp
            msg = {
                "uuid": uuid,
                "ts": unix_timestamp_to_iso(latest),
                "content": f'data:image/jpeg;base64,{base64.b64encode(content).decode()}',
                "index": n,
            }
            images.append(msg)
            n+=1
        except:
            break
    return int((latest-oldest)/1_000_000), images


@login_required
def images_view(request):
    cursid, expid, duration, uuid, images = 0, None, 0, "", []    
    if request.method == 'POST':
        cursid = request.POST.get('_sid')
        expid = request.POST.get('_expid')
        uuid = request.POST.get('_multiwell')
        duration, images = get_images(uuid)

    current_session = models.Session.get_session(cursid)
    experiments, current_experiment = get_not_active_experiments(current_session, expid)
    ctx = dict(
        choice_title=_("Gestionnaire d'images"),
        sessions=models.Session.objects.filter(active=False).all(),
        experiments=experiments or [],
        current_session=current_session,
        current_experiment=current_experiment,
        images=images,
        uuid=uuid,
        duration=duration,
    )
    return render(request, "scanner/images.html", context=global_context(request, **ctx))


## replay
@require_POST
@csrf_exempt
def download_api(request):
    data = json.loads(request.body.decode() or "{}")
    action = data.get("action")
    if action=='download':
        uuid, dt_start, dt_stop, frame_rate = data.get("uuid"), data.get("dt_start"), data.get("dt_stop"), data.get("fps")
        return download_video.delay(uuid, dt_start, dt_stop, frame_rate=frame_rate)  # @UndefinedVariable
    else:
        return JsonResponse({"state":  False})


def get_video(uuid):
    oldest, latest = async_to_sync(reductstore.old_last_dates)(cameraDB, entry_name=uuid)
    filters = record_manager.set_filters(test=False)
    image, _ =  record_manager.first_image(uuid, filters=filters)
    return oldest, latest, image


@login_required
def replay_view(request):
    cursid, expid, oldest, latest, uuid, image = 0, None, 0, 0, "", ""

    if request.method == 'POST':
        cursid = request.POST.get('_sid')
        expid = request.POST.get('_expid')
        uuid = request.POST.get('_multiwell')
        if uuid:
            oldest, latest, image = get_video(uuid)
            
    current_session = models.Session.get_session(cursid)
    experiments, current_experiment = get_not_active_experiments(current_session, expid)            
    ctx = dict(
        choice_title=_("Gestionnaire de vidéos"),
        ws_route=settings.REPLAY_WEBSOCKET_ROUTE,
        sessions=models.Session.objects.filter(active=False).all(),
        experiments=experiments or [],
        current_session=current_session,
        current_experiment=current_experiment,        
        image=image,
        uuid=uuid,
        oldest=oldest,
        latest=latest,
    )
    return render(request, "scanner/replay.html", context=global_context(request, **ctx))

@require_POST
@csrf_exempt
def export_api(request):
    data = json.loads(request.body.decode() or "{}")
    session_id = data.get("sid")
    action = data.get("action")
    
    if action == 'export_images':
        export_all_images(session_id)
        return JsonResponse({"success":  True,  "msg": str(_("Images téléchargées"))})
    elif action == 'export_videos':
        export_all_videos(session_id)
        return JsonResponse({"success":  True, "msg": str(_("Vidéos téléchargées"))})
    else:
        return JsonResponse({"success":  False, "msg": str(_("Erreur d'exportation"))})    


