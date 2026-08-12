from django.urls import path

from . import views


urlpatterns = [
    path("", views.import_list, name="import_list"),
    path("<int:batch_id>/", views.import_detail, name="import_detail"),
    path("<int:batch_id>/replace/", views.import_replace, name="import_replace"),
]
