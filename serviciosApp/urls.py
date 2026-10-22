from django.urls import path
from . import views

urlpatterns = [
    path('servicios/', views.servicios, name='servicios'),
    path('servicios/detalle/<int:pk>/', views.detalle_servicio, name='detalle_servicio'),
]
