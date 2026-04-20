from django.contrib import admin
from django.db.models import Q
from . import models

class WellAdmin(admin.ModelAdmin):
    model = models.Well
    list_display = ('name', 'author',)

class ConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'author', 'use_rpicam', 'video_width_capture', 'video_height_capture', 'video_frame_rate', 'px_per_mm', 'active',)

class MultiWellAdmin(admin.ModelAdmin):
    list_filter = ('author', )
    list_display = ('label', 'position', 'author', 'order', 'xbase', 'ybase', 'duration', 'feed', 'default', 'well_position', 'active',)

class WellPositionAdmin(admin.ModelAdmin):
    list_filter = ('author', 'multiwell')
    list_display = ('multiwell__position', 'well__name', 'order', 'x', 'y', 'author',)
    

class ObservationMultiWellDetailInline(admin.TabularInline):
    model = models.ObservationMultiWellDetail
    extra = 0

class ObservationAdmin(admin.ModelAdmin):
    inlines = (ObservationMultiWellDetailInline,)
    list_filter = ('sessionobservation__session', 'author', )
    list_display = ('title', 'author',  'multiwell', 'created', 'started', 'finished')
    readonly_fields = ('created',  'started',  'finished', )

class SessionObservationInlineAdmin(admin.TabularInline):
    model = models.SessionObservation
    fk_name = 'session'
    extra = 0

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "observation":
            obj_id = request.resolver_match.kwargs.get("object_id")

            qs = models.Observation.objects.filter(sessionobservation__isnull=True)
            if obj_id:
                qs = models.Observation.objects.filter(
                    Q(sessionobservation__isnull=True) |
                    Q(sessionobservation__session_id=obj_id)
                )
            kwargs["queryset"] = qs.distinct()

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

class SessionAdmin(admin.ModelAdmin):
    list_filter = ('author',)
    inlines = (SessionObservationInlineAdmin, )
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
admin.site.register(models.WellPostion, WellPositionAdmin)
admin.site.register(models.Observation, ObservationAdmin)
admin.site.register(models.Session, SessionAdmin)
