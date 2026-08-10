from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("pages.urls")),
    path("Rasel/", include("rasel.urls")),
    path("Referrals/", include("referrals.urls")),
    path("Account/", include("account.urls")),
]
