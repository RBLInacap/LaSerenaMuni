from django.db.models import Q
from django.shortcuts import render
from serviciosApp.models import Servicio
from .models import Solicitud


def inicio(request):
    titulo = "Municipalidad de La Serena"
    mensaje = "Sistema de gestión y seguimiento de solicitudes ciudadanas"
    servicios = Servicio.objects.select_related('categoria').order_by('nombre')
    total_servicios = servicios.count()
    usuario = "Funcionario municipal"
    es_admin = True

    if es_admin:
        estado = "Acceso autorizado"
    else:
        estado = "Acceso restringido"

    contexto = {
        "titulo": titulo,
        "mensaje": mensaje,
        "servicios": servicios,
        "total_servicios": total_servicios,
        "usuario": usuario,
        "estado": estado,
    }
    return render(request, 'inicio.html', contexto)


def solicitudes(request):
    busqueda = request.GET.get('q', '').strip()
    solicitudes_lista = Solicitud.objects.all().order_by('id')

    if busqueda:
        solicitudes_lista = solicitudes_lista.filter(
            Q(nombre__icontains=busqueda)
            | Q(estado__icontains=busqueda)
            | Q(sector__icontains=busqueda)
            | Q(descripcion__icontains=busqueda)
        )

    cantidad = solicitudes_lista.count()
    contexto = {
        "solicitudes_lista": solicitudes_lista,
        "cantidad": cantidad,
        "busqueda": busqueda,
    }
    return render(request, 'solicitudes.html', contexto)


def acerca(request):
    nombre_proyecto = "Portal de Solicitudes Municipales"
    version = "1.0.0"
    tecnologias = ["Python", "Django", "Bootstrap", "MySQL y ORM"]
    contexto = {
        "nombre_proyecto": nombre_proyecto,
        "version": version,
        "tecnologias": tecnologias,
    }
    return render(request, 'acerca.html', contexto)