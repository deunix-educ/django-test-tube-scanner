from django.contrib import admin
from django.db.models import Q
from . import models


class WellAdmin(admin.ModelAdmin):
    model = models.Well
    list_display = ('name', 'author',)

class ConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'author', 'capture_type', 'video_width_capture', 'video_height_capture', 'video_frame_rate', 'active',)

class MultiWellAdmin(admin.ModelAdmin):
    list_filter = ('author', )
    list_display = ('label', 'position', 'author', 'order', 'xbase', 'ybase', 'duration', 'feed', 'default', 'well_position', 'active',)

class WellPositionAdmin(admin.ModelAdmin):
    list_filter = ('author', 'multiwell')
    list_display = ('multiwell__position', 'well__name', 'order', 'x', 'y', 'px_per_mm', 'author',)
    

#class ExperimentConfigInline(admin.TabularInline):
#    model = models.ExperimentConfig
#    extra = 0

class ExperimentAdmin(admin.ModelAdmin):
    #inlines = (ExperimenConfigInline,)
    list_filter = ('session_experiments__session', 'author', )
    list_display = ('title', 'author',  'multiwell', 'created', 'started', 'finished')
    readonly_fields = ('created',  'started',  'finished', )

class SessionExperimentInlineAdmin(admin.TabularInline):
    model = models.SessionExperiment
    fk_name = 'session'
    extra = 0

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "experiment":
            obj_id = request.resolver_match.kwargs.get("object_id")

            qs = models.Experiment.objects.filter(session_experiments__isnull=True)
            if obj_id:
                qs = models.Experiment.objects.filter(
                    Q(session_experiments__isnull=True) |
                    Q(session_experiments__session_id=obj_id)
                )
            kwargs["queryset"] = qs.distinct()

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

class SessionAdmin(admin.ModelAdmin):
    list_filter = ('author',)
    inlines = (SessionExperimentInlineAdmin, )
    list_display = ('name', 'author', 'created', 'finished', 'active', 'expected_export', 'expected_scanning', )
    readonly_fields = (
        'created', 
        'finished',
        'export_status',
        'export_task', 
        'export_exported_at', 
        'scanning_status',
        'scanning_task', 
        'scanning_finished_at'
    )

admin.site.register(models.Configuration, ConfigurationAdmin)
admin.site.register(models.Well, WellAdmin)
admin.site.register(models.MultiWell, MultiWellAdmin)
admin.site.register(models.WellPosition, WellPositionAdmin)
admin.site.register(models.Experiment, ExperimentAdmin)
admin.site.register(models.Session, SessionAdmin)

