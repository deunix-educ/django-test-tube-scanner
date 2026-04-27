# planarian/urls.py

from django.urls import path
from planarian import views

app_name = "planarian"

urlpatterns = [
    # Configurations expériences
    path("experiments/",         views.ExperimentConfigListView.as_view(), name="experiment-list"),
    path("experiments/new/",     views.ExperimentConfigFormView.as_view(), name="experiment-new"),
    path("experiments/<int:pk>/",views.ExperimentConfigFormView.as_view(), name="experiment-edit"),

    # Import / export
    path("import/",              views.ImportParamsView.as_view(),         name="import-params"),
    path("export/",              views.ExportCsvView.as_view(),            name="export-csv"),

    # API JSON pour le front-end
    path("api/tracking/",        views.TrackingDataView.as_view(),         name="tracking-data-api"),
]

