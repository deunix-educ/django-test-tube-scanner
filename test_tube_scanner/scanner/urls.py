
from django.urls import path
from . import views

app_name = "scanner"

urlpatterns = [
    path('scanner/admin/', views.admin_view, name='admin'),
    path('scanner/reductstore/', views.reductstore_view, name='reductstore'),
    path('scanner/adminer/', views.adminer_view, name='adminer'),
    path('scanner/portainer/', views.portainer_view, name='portainer'),
    path('scanner/calibration/', views.calibration_view, name='calibration'),
    path('scanner/supervisor/', views.supervisor_view, name='supervisor'),
    path('scanner/logs/worker', views.supervisor_worker, name='logs_worker'),
    path('scanner/logs/scheduler', views.supervisor_scheduler, name='logs_scheduler'),
    
    path('main/', views.main_view, name='main'),
    path('scanner/images/', views.images_view, name='images'),
    path('scanner/replay/', views.replay_view, name='replay'),
    path('api/stats/', views.stats_view, name='api_stats'),
    path('api/video/', views.download_api, name='download_api'),
    path('api/export/', views.export_api, name='export_api'),
]
