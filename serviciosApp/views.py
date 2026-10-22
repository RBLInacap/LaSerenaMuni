from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from .models import Servicio


def servicios(request):
    busqueda = request.GET.get('q', '').strip()
    servicios_lista = Servicio.objects.select_related('categoria').prefetch_related('requisitos').all().order_by('id')

    if busqueda:
        servicios_lista = servicios_lista.filter(
            Q(nombre__icontains=busqueda)
            | Q(categoria__nombre__icontains=busqueda)
            | Q(descripcion__icontains=busqueda)
        )

    cantidad = servicios_lista.count()
    contexto = {
        "servicios_lista": servicios_lista,
        "cantidad": cantidad,
        "busqueda": busqueda,
    }
    return render(request, 'servicios.html', contexto)


def detalle_servicio(request, pk):
    servicio = get_object_or_404(Servicio, pk=pk)
    return render(request, 'servicios_detalle.html', {"servicio": servicio})

