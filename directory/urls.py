from django.urls import path

from . import views


urlpatterns = [
    path("doctors/", views.doctor_list, name="doctor_list"),
    path("doctors/new/", views.doctor_create, name="doctor_create"),
    path("doctors/<int:doctor_id>/edit/", views.doctor_edit, name="doctor_edit"),
    path("departments/", views.department_list, name="department_list"),
    path("departments/new/", views.department_create, name="department_create"),
    path(
        "departments/<int:department_id>/edit/",
        views.department_edit,
        name="department_edit",
    ),
]
