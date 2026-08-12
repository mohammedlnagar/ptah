from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("pages.urls")),
    path("Rasel/", include("rasel.urls")),
    path("Account/", include("account.urls")),
    path("Directory/", include("directory.urls")),
    path("Messaging/", include("messaging.urls")),
]
