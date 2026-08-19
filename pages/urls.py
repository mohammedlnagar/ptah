
from django.urls import path
from .views import healthz, home

urlpatterns = [
    path('', home, name='home'),
    path('healthz/', healthz, name='healthz'),
]
