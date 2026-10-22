from django.contrib import admin
from .models import Solicitud


class SolicitudAdmin(admin.ModelAdmin):
	list_display = ('nombre', 'estado', 'sector')
	search_fields = ('nombre', 'estado', 'sector', 'descripcion')
	list_filter = ('estado', 'sector')


admin.site.register(Solicitud, SolicitudAdmin)
