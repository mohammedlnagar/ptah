from django.urls import path

from . import views


urlpatterns = [
    path("templates/", views.template_approvals, name="template_approvals"),
    path(
        "templates/<int:revision_id>/submit/",
        views.submit_template,
        name="submit_template",
    ),
    path(
        "templates/<int:revision_id>/approve/",
        views.approve_template,
        name="approve_template",
    ),
    path(
        "templates/<int:revision_id>/reject/",
        views.reject_template,
        name="reject_template",
    ),
]
