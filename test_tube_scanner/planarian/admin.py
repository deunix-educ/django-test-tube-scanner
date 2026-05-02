# planarian/admin.py

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import ExperimentConfig


@admin.register(ExperimentConfig)
class ExperimentConfigAdmin(admin.ModelAdmin):
    """Admin Django pour les configurations d'expérience."""
    #readonly_fields = ('experiment',  )
    readonly_fields = ("identifier", 'px_per_mm',  'fps', 'well_radius_mm',)
    list_display  = ("experiment", "well", "px_per_mm", "fps",
                     "thresh_immobile", "thresh_mobile",
                     "photo_mode", "chemo_strength", "created_at")
    list_filter   = ("photo_mode", "tube_axis")
    search_fields = ("experiment", "well", "description")
    ordering      = ("-created_at",)

    fieldsets = (
        (_("Identification"), {
            "fields": ("identifier", "experiment", "well", "description"),
        }),        
        (_("Calibration optique"), {
            "fields": ("px_per_mm", "fps", "well_radius_mm"),
            "classes": ("collapse",),
        }),
        (_("Seuils de mobilité EthoVision"), {
            "fields": ("thresh_immobile", "thresh_mobile"), 
            "classes": ("collapse",),
        }),
        (_("Tracker"), {
            "fields": ("tube_axis", "min_area_px", "max_area_ratio", "planarian_count"),
            "classes": ("collapse",),
        }),
        (_("Thigmotactisme"), {
            "fields": ("thigmotaxis_wall_dist_mm",),
            "classes": ("collapse",),
        }),
        (_("Phototactisme"), {
            "fields": ("photo_mode", "photo_strength", "photo_x", "photo_y"),
            "classes": ("collapse",),
        }),
        (_("Chimiotactisme"), {
            "fields": ("chemo_strength", "chemo_x", "chemo_y", "chemo_radius_mm"),
            "classes": ("collapse",),
        }),
        (_("Interactions inter-individus"), {
            "fields": ("avoid_radius_mm", "aggreg_radius_mm"),
            "classes": ("collapse",),
        }),
    )

    # Action : export CSV template
    actions = ["export_csv_template"]

    @admin.action(description=_("Exporter un template CSV de ces configurations"))
    def export_csv_template(self, request, queryset):
        import csv
        from django.http import HttpResponse
        from io import StringIO

        output = StringIO()
        fields = [f.name for f in ExperimentConfig._meta.fields if f.name != "id"]  # @UndefinedVariable
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for obj in queryset:
            row = {f: getattr(obj, f) for f in fields}
            writer.writerow(row)

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="experiment_configs.csv"'
        
        return response

