from django.urls import include, path


# Mirrors wasel.urls minus the admin so that view tests can render templates
# that extend base.html, which reverses home, logout, profile and
# manage_appointments.
urlpatterns = [
    path("", include("pages.urls")),
    path("Rasel/", include("rasel.urls")),
    path("Account/", include("account.urls")),
    path("Directory/", include("directory.urls")),
    path("Messaging/", include("messaging.urls")),
]
