from django.urls import path
from . import views

urlpatterns = [
    path('', views.inicio, name='home'),
    path('solicitudes/', views.solicitudes, name='solicitudes'),
    path('acerca/', views.acerca, name='acerca'),
]
