
from django.urls import path
from . import views

app_name = "scanner"

urlpatterns = [
    path('admin/', views.admin_view, name='admin'),
    path('reductstore/', views.reductstore_view, name='reductstore'),
    path('adminer/', views.adminer_view, name='adminer'),
    path('portainer/', views.portainer_view, name='portainer'),
    path('calibration/', views.calibration_view, name='calibration'),
    path('supervisor/', views.supervisor_view, name='supervisor'),
    path('logs/worker', views.supervisor_worker, name='logs_worker'),
    path('logs/scheduler', views.supervisor_scheduler, name='logs_scheduler'),
    
    path('main/', views.main_view, name='main'),
    path('images/', views.images_view, name='images'),
    path('replay/', views.replay_view, name='replay'),
    path('api/stats/', views.stats_view, name='api_stats'),
    path('api/video/', views.download_api, name='download_api'),
    path('api/export/', views.export_api, name='export_api'),
]
