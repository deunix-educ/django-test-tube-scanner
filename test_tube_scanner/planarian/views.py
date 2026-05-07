# planarian/views.py

#import asyncio
import logging

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect    #, render
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import FormView, ListView
from django.views.decorators.http import require_GET

from .forms import CsvImportForm, ExperimentConfigForm, ExportCsvForm
from .models import ExperimentConfig
from modules.planarian_metrics import ExperimentParams, ReductStoreClient
from modules.system_stats import get_cached_stats, start_background_updater
from scanner.constants import ScannerConstants


logger = logging.getLogger(__name__)

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
    conf = ScannerConstants().get()
    return dict(
        app_title=settings.APP_TITLE,
        app_sub_title=settings.APP_SUB_TITLE,
        domain_server=settings.DOMAIN_SERVER,
        conf=conf,
        **ctx
    )


def _get_reduct_client() -> ReductStoreClient:
    """Instancie le client ReductStore depuis les settings Django."""
    return ReductStoreClient(url=settings.REDUCTSTORE_URL, token=settings.REDUCTSTORE_TOKEN)


# ---------------------------------------------------------------------------
# Vue : liste des configurations
# ---------------------------------------------------------------------------

class ExperimentConfigListView(ListView):
    """Liste toutes les configurations expériences."""

    model               = ExperimentConfig
    template_name       = "planarian/experiment_list.html"
    context_object_name = "configs"
    ordering            = ["-created_at"]
    
    '''
    def get_queryset(self):
        # Récupérer le queryset de base
        queryset = ExperimentConfig.objects.filter(experiment__session_experiments__isnull=False).select_related()
        return queryset'''
    
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return global_context(self.request, **context)
    
    

# ---------------------------------------------------------------------------
# Vue : création / modification d'une configuration
# ---------------------------------------------------------------------------

class ExperimentConfigFormView(FormView):
    """Formulaire de saisie des paramètres d'une expérience."""

    template_name = "planarian/experiment_form.html"
    form_class    = ExperimentConfigForm


    def get_form(self, form_class=None):
        pk = self.kwargs.get("pk")
        if pk:
            instance = get_object_or_404(ExperimentConfig, pk=pk)
            return ExperimentConfigForm(self.request.POST or None, instance=instance)
        return ExperimentConfigForm(self.request.POST or None)

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Configuration sauvegardée."))
        return redirect("planarian:experiment-list")
    
    def form_invalid(self, form):
        # Called when form validation fails
        print(f"Form validation failed: {form.errors}")
        messages.error(self.request, form.errors)
        return super().form_invalid(form)   

    #def post(self, request, *args, **kwargs):
    #    # Custom logic before processing the form
    #    print(f"Received POST data: {request.POST}")
    #    return response       

    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)    
        context['is_creation'] = 'pk' not in self.kwargs
        context['is_update'] = 'pk' in self.kwargs
        return global_context(self.request, choice_title=_("Paramètres d'une expérience"), **context)
    

# ---------------------------------------------------------------------------
# Vue : import CSV de paramètres
# ---------------------------------------------------------------------------

class ImportParamsView(FormView):
    """
    Import de configurations d'expérience depuis un fichier CSV.
    Une ligne CSV = un puits = un ExperimentConfig.

    Colonnes CSV obligatoires : experiment, well, px_per_mm, fps
    Toutes les autres colonnes correspondent aux champs du modèle.
    """

    template_name = "planarian/import_params.html"
    form_class    = CsvImportForm

    def form_valid(self, form):
        rows      = form.csv_rows
        overwrite = form.cleaned_data["overwrite"]
        created   = 0
        updated   = 0
        errors    = 0

        for row in rows:
            try:
                params = ExperimentParams.from_csv_row(row)
                d      = params.to_dict()

                obj, is_new = ExperimentConfig.objects.get_or_create(
                    experiment = d["experiment"],
                    well       = d["well"],
                )

                if is_new or overwrite:
                    for k, v in d.items():
                        if k not in ("experiment", "well") and hasattr(obj, k):
                            setattr(obj, k, v)
                    obj.save()
                    if is_new:
                        created += 1
                    else:
                        updated += 1

            except Exception as e:
                logger.warning(f"Ligne ignorée ({row}): {e}")
                errors += 1

        messages.success(
            self.request,
            _("Import terminé : %(c)d créés, %(u)d mis à jour, %(e)d erreurs.")
            % {"c": created, "u": updated, "e": errors},
        )
        return redirect("planarian:experiment-list")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return global_context(self.request, choice_title=_("configurations d'expérience depuis un fichier CSV"), **context)
    


# ---------------------------------------------------------------------------
# Vue : export CSV depuis ReductStore
# ---------------------------------------------------------------------------

class ExportCsvView(FormView):
    """
    Export des données de tracking depuis ReductStore vers un fichier CSV.
    Retourne le fichier en téléchargement HTTP.
    """

    template_name = "planarian/export_csv.html"
    form_class    = ExportCsvForm

    def form_valid(self, form):
        d = form.cleaned_data
        
        @async_to_sync
        async def _do_export():
            client = _get_reduct_client()
            await client.connect()
            try:
                csv_content, n = await client.export_csv_response(
                    experiment  = d["experiment"],
                    well        = d["well"],
                    planarian   = d["planarian"],
                    record_type = d["record_type"],
                    start       = d.get("start_dt"),
                    stop        = d.get("stop_dt"),
                )          
                print(f"Export CSV: export_csv_response done, {n} lignes, content size={len(csv_content)}, {csv_content}")
            except Exception as e:
                logger.error(f"Erreur export CSV: {e}")
                messages.error(self.request, _("Erreur lors de l'export CSV: %(error)s") % {"error": str(e)})
                return None, 0
            
            return csv_content, n

        csv_content, n = _do_export()

        print(f"Export CSV: {n} lignes, content size={len(csv_content)}")
        if not csv_content:
            messages.warning(self.request, _("Aucune donnée trouvée."))
            return self.form_invalid(form)

        filename = (
            f"{d['experiment']}_{d['well']}_planaire{d['planarian']}"
            f"_{d['record_type']}.csv"
        )
        response = HttpResponse(csv_content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'       
        messages.success(self.request, _("%(n)d lignes exportées.") % {"n": n})
        return response
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return global_context(self.request, choice_title=_("Tracking depuis ReductStore vers un fichier CSV"), **context)
    

# ---------------------------------------------------------------------------
# Vue API JSON : données de tracking (pour polling front-end)
# ---------------------------------------------------------------------------

class TrackingDataView(View):
    """
    API JSON retournant les métriques de tracking d'un planaire.
    Utilisable pour un affichage temps réel ou un graphe front-end.

    GET /tracking-data/?experiment=X&well=Y&planarian=0&record_type=frame
    """

    def get(self, request):
        experiment  = request.GET.get("experiment", "")
        well        = request.GET.get("well", "")
        planarian   = int(request.GET.get("planarian", 0))
        record_type = request.GET.get("record_type", "frame")

        if not experiment or not well:
            return JsonResponse({"error": "experiment et well requis"}, status=400)

        @async_to_sync
        async def _fetch():
            client = _get_reduct_client()
            await client.connect()
            try:
                return await client.get_tracking_data(
                    experiment  = experiment,
                    well        = well,
                    planarian   = planarian,
                    record_type = record_type,
                )
            except Exception as e:
                logger.error(f"Erreur fetching tracking data: {e}")

        records = _fetch()
        return JsonResponse({"count": len(records), "records": records})
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return global_context(self.request, choice_title=_("Métriques de tracking d'un planaire"), **context)
    
