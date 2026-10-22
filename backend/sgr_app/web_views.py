from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
import re
import base64
import binascii
import hashlib
import hmac
import time
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.contrib.auth.decorators import login_not_required
from sgr_app.forms import MiFichaPersonalForm, SolicitanteForm
from sgr_app.periodos import get_nombre_trimestre_actual, get_periodo_trimestre_actual
from sgr_app.models import (
    Delegacion, Cargo, Usuario, PeriodoMedicion, ItemMedicion,
    Actividad, Evidencia, CompromisoAgenda, CasoSocial, AtencionSocial, Solicitante,
    RegistroAuditoria
)
from sgr_app.services.calculos import (
    calcular_metricas_funcionario,
    calcular_resumen_delegacion,
    calcular_resumen_comunal,
    determinar_color_semaforo
)

ACTIVIDAD_TERRITORIOS = (
    'Sector Centro', 'El Milagro', 'La Pampa', 'Las Compañías',
    'La Antena', 'Avenida del Mar', 'Sector Rural', 'Otro',
)
ACTIVIDAD_AREAS_APOYO = (
    'Operaciones y Territorio', 'Alumbrado Público', 'Aseo y Ornato',
    'DIDECO / Social', 'Tránsito y Transporte', 'Seguridad Ciudadana',
    'Medio Ambiente', 'SECPLAN / Proyectos',
)

def es_codigo_2fa_valido(user, code):
    secret = getattr(user, 'totp_secret', None)
    if not secret or not re.fullmatch(r'\d{6}', code or ''):
        return False
    try:
        key = base64.b32decode(secret.upper() + '=' * (-len(secret) % 8), casefold=True)
    except (binascii.Error, ValueError):
        return False
    counter = int(time.time()) // 30
    for candidate in range(counter - 1, counter + 2):
        digest = hmac.new(key, candidate.to_bytes(8, 'big'), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        value = int.from_bytes(digest[offset:offset + 4], 'big') & 0x7FFFFFFF
        expected = f'{value % 1_000_000:06d}'
        if hmac.compare_digest(expected, code):
            return True
    return False

def get_periodo_activo():
    return PeriodoMedicion.objects.filter(cerrado=False).order_by('-fecha_inicio', '-id').first() or PeriodoMedicion.objects.order_by('-fecha_inicio', '-id').first()


def _puede_gestionar_compromiso(user, compromiso=None):
    if user.is_superuser or user.rol in (Usuario.Rol.ADMIN, Usuario.Rol.COORDINADOR):
        return True
    if user.rol == Usuario.Rol.DELEGADO:
        return bool(user.delegacion_id and compromiso and compromiso.delegacion_id == user.delegacion_id)
    return bool(
        user.rol == Usuario.Rol.FUNCIONARIO
        and compromiso
        and compromiso.creado_por_id == user.pk
        and compromiso.responsable_id == user.pk
    )

@login_not_required
def web_login(request):
    if request.user.is_authenticated:
        if request.user.rol == Usuario.Rol.FUNCIONARIO:
            return redirect('web_personal')
        return redirect('web_dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        code_2fa = request.POST.get('code_2fa', '').strip()

        if not username and not password:
            return render(request, 'login.html', {'error': 'Usuario y contraseña son obligatorios.'})
        if not username:
            return render(request, 'login.html', {'error': 'El nombre de usuario es obligatorio.'})
        if not password:
            return render(request, 'login.html', {'error': 'La contraseña es obligatoria.'})

        user_obj = Usuario.objects.filter(username=username).first()
        if user_obj and not user_obj.is_active:
            return render(request, 'login.html', {'error': 'Usuario bloqueado o inactivo.'})

        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Flujo 2FA
            if user.requires_2fa:
                request.session['pending_2fa_user_id'] = user.pk
                request.session.set_expiry(300)
                if code_2fa:
                    if es_codigo_2fa_valido(user, code_2fa):
                        request.session.pop('pending_2fa_user_id', None)
                        login(request, user)
                        RegistroAuditoria.objects.create(
                            usuario=user, accion='INICIO_SESION_2FA', entidad='Usuario',
                            identificador_registro=str(user.id),
                            ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1')
                        )
                        messages.success(request, f"¡Sesión iniciada con éxito! Autenticación 2FA verificada para {user.get_full_name() or user.username}.")
                        if user.rol == Usuario.Rol.FUNCIONARIO:
                            return redirect('web_personal')
                        return redirect('web_dashboard')
                    else:
                        return render(request, 'login.html', {
                            'error': 'Código 2FA incorrecto. Ingrese el código temporal de 6 dígitos generado por su dispositivo.',
                            'show_2fa_checked': True,
                            'username_val': username
                        })
                else:
                    return render(request, 'login.html', {
                        'show_2fa': True,
                        'user_id': user.id
                    })

            login(request, user)
            RegistroAuditoria.objects.create(
                usuario=user, accion='INICIO_SESION', entidad='Usuario',
                identificador_registro=str(user.id),
                valor_nuevo={'username': user.username},
                ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1')
            )
            if user.rol == Usuario.Rol.FUNCIONARIO:
                return redirect('web_personal')
            return redirect('web_dashboard')
        else:
            return render(request, 'login.html', {
                'error': 'Credenciales inválidas.',
                'username_val': username,
                'show_2fa_checked': False
            })

    return render(request, 'login.html')

@login_not_required
def web_verificar_2fa(request):
    if request.method == 'POST':
        user_id = request.session.get('pending_2fa_user_id')
        code = request.POST.get('code', '').strip()
        if not user_id:
            return redirect('web_login')
        try:
            user = Usuario.objects.get(id=user_id, is_active=True, requires_2fa=True)
            if es_codigo_2fa_valido(user, code):
                request.session.pop('pending_2fa_user_id', None)
                login(request, user)
                RegistroAuditoria.objects.create(
                    usuario=user, accion='VERIFICACION_2FA', entidad='Usuario',
                    identificador_registro=str(user.id),
                    ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1')
                )
                messages.success(request, f"¡Autenticación 2FA confirmada para {user.get_full_name() or user.username}!")
                if user.rol == Usuario.Rol.FUNCIONARIO:
                    return redirect('web_personal')
                return redirect('web_dashboard')
            else:
                return render(request, 'login.html', {
                    'show_2fa': True,
                    'user_id': user.pk,
                    'error': 'Código 2FA incorrecto. Verifique el token de 6 dígitos en su dispositivo e intente nuevamente.'
                })
        except Usuario.DoesNotExist:
            request.session.pop('pending_2fa_user_id', None)
            return redirect('web_login')
    return redirect('web_login')

def web_logout(request):
    logout(request)
    return redirect('web_login')

def web_dashboard(request):
    if request.user.is_authenticated and request.user.rol == Usuario.Rol.FUNCIONARIO:
        messages.info(request, "Acceso redirigido: Como Funcionario de Terreno tienes asignado tu Dashboard Personal de cumplimiento individual.")
        return redirect('web_personal')

    periodo, periodo_configurado = get_periodo_trimestre_actual()
    periodo_nombre_actual = get_nombre_trimestre_actual()
    delegaciones = Delegacion.objects.filter(activo=True)
    total_delegaciones = delegaciones.count()
    
    del_id_param = request.GET.get('delegacion_id')
    delegacion_seleccionada = None
    if del_id_param:
        try:
            delegacion_seleccionada = int(del_id_param)
        except ValueError:
            pass

    comunal = calcular_resumen_comunal(periodo) if periodo else None
    
    if delegacion_seleccionada and comunal:
        delegaciones_filtradas = [d for d in comunal['delegaciones'] if d['delegacion_id'] == delegacion_seleccionada]
    else:
        delegaciones_filtradas = comunal['delegaciones'] if comunal else []

    total_funcionarios = sum(d['total_funcionarios'] for d in delegaciones_filtradas)
    total_pendientes_check = sum(d['evidencias_pendientes_check'] for d in delegaciones_filtradas)
    total_vencidos = sum(d['compromisos']['vencidos'] for d in delegaciones_filtradas)
    
    if delegaciones_filtradas:
        promedio_ponderado = round(sum(d['promedio_ponderado_pct'] for d in delegaciones_filtradas) / len(delegaciones_filtradas), 1)
    else:
        promedio_ponderado = 0.0

    meta_esp = comunal['meta_esperada_pct'] if comunal else 0.0
    semaforo_promedio = determinar_color_semaforo(
        promedio_ponderado,
        meta_esp,
        periodo.umbral_semaforo_verde if periodo else 100.0,
        periodo.umbral_semaforo_ambar if periodo else 60.0,
    )
    
    funcionarios_lista = []
    for d in delegaciones_filtradas:
        funcionarios_lista.extend(d['funcionarios'])

    return render(request, 'dashboard_general.html', {
        'comunal': comunal,
        'periodo': periodo,
        'periodo_configurado': periodo_configurado,
        'periodo_nombre_actual': periodo_nombre_actual,
        'delegaciones': delegaciones,
        'total_delegaciones': total_delegaciones,
        'delegacion_seleccionada': delegacion_seleccionada,
        'total_funcionarios': total_funcionarios,
        'total_pendientes_check': total_pendientes_check,
        'total_vencidos': total_vencidos,
        'promedio_ponderado': promedio_ponderado,
        'semaforo_promedio': semaforo_promedio,
        'funcionarios_lista': funcionarios_lista,
    })

def web_semaforo(request):
    periodo, periodo_configurado = get_periodo_trimestre_actual()
    delegaciones = Delegacion.objects.filter(activo=True)
    
    del_id_param = request.GET.get('delegacion_id')
    delegacion_seleccionada = None
    if del_id_param:
        try:
            delegacion_seleccionada = int(del_id_param)
        except ValueError:
            pass

    comunal = calcular_resumen_comunal(periodo) if periodo else None
    
    if delegacion_seleccionada and comunal:
        delegaciones_filtradas = [d for d in comunal['delegaciones'] if d['delegacion_id'] == delegacion_seleccionada]
    else:
        delegaciones_filtradas = comunal['delegaciones'] if comunal else []

    meta_esperada_pct = comunal['meta_esperada_pct'] if comunal else 0.0
    umbral_verde = periodo.umbral_semaforo_verde if periodo else 100.0
    umbral_ambar = periodo.umbral_semaforo_ambar if periodo else 60.0
    umbral_60_dia = comunal['info_tiempo']['umbral_60_dia'] if comunal else 0.0

    funcionarios_semaforo = []
    for d in delegaciones_filtradas:
        for f in d['funcionarios']:
            avance = f['total_ponderado_pct']
            color = determinar_color_semaforo(avance, meta_esperada_pct, umbral_verde, umbral_ambar)
            funcionarios_semaforo.append({
                'id': f['funcionario_id'],
                'area': f.get('cargo') or 'Gestión Territorial',
                'responsable': f.get('nombre_completo') or f.get('username'),
                'delegacion': d.get('nombre') or f.get('delegacion_codigo', 'Central'),
                'objetivo_al_dia': meta_esperada_pct,
                'umbral_60': umbral_60_dia,
                'avance_real': avance,
                'color_semaforo': color,
                'dias_sin_ingreso': f.get('dias_sin_ingreso'),
            })

    funcionarios_semaforo.sort(key=lambda x: x['avance_real'], reverse=True)

    if funcionarios_semaforo:
        promedio_avance = round(sum(f['avance_real'] for f in funcionarios_semaforo) / len(funcionarios_semaforo), 2)
        color_promedio = determinar_color_semaforo(
            promedio_avance, meta_esperada_pct, umbral_verde, umbral_ambar
        )
    else:
        promedio_avance = 0.0
        color_promedio = 'AMBAR'

    return render(request, 'semaforo_al_dia.html', {
        'comunal': comunal,
        'periodo': periodo,
        'periodo_configurado': periodo_configurado,
        'delegaciones': delegaciones,
        'delegacion_seleccionada': delegacion_seleccionada,
        'funcionarios_semaforo': funcionarios_semaforo,
        'meta_esperada_pct': meta_esperada_pct,
        'umbral_60_dia': umbral_60_dia,
        'umbral_verde': umbral_verde,
        'umbral_ambar': umbral_ambar,
        'promedio_avance': promedio_avance,
        'color_promedio': color_promedio,
    })

def web_personal(request):
    periodo, periodo_configurado = get_periodo_trimestre_actual()
    todos_funcionarios = Usuario.objects.filter(rol=Usuario.Rol.FUNCIONARIO, is_active=True).select_related('delegacion', 'cargo')
    
    # Si el usuario logueado es Funcionario, solo puede ver su propia ficha personal
    if request.user.is_authenticated and request.user.rol == Usuario.Rol.FUNCIONARIO:
        funcionario = request.user
    else:
        id_param = request.GET.get('id')
        funcionario = None
        if id_param:
            funcionario = Usuario.objects.filter(id=id_param).first()
        elif todos_funcionarios.exists():
            funcionario = todos_funcionarios.first()

    metricas = None
    actividades = []
    items_funcionario = []
    if funcionario:
        actividades = Actividad.objects.filter(funcionario=funcionario).select_related(
            'item_medicion', 'delegacion', 'compromiso_agenda'
        ).prefetch_related('evidencias', 'compromisos').order_by('-fecha_actividad', '-fecha_registro')[:50]
        if periodo:
            metricas = calcular_metricas_funcionario(funcionario, periodo)
            if periodo.pk and funcionario.cargo:
                items_funcionario = list(ItemMedicion.objects.filter(periodo=periodo, cargo=funcionario.cargo, activo=True))
            if periodo.pk and not items_funcionario:
                items_funcionario = list(ItemMedicion.objects.filter(periodo=periodo, activo=True))

    areas_apoyo = [
        'Operaciones y Territorio',
        'Alumbrado Público',
        'Aseo y Ornato',
        'DIDECO / Social',
        'Tránsito y Transporte',
        'Seguridad Ciudadana',
        'Medio Ambiente',
        'SECPLAN / Proyectos'
    ]

    return render(request, 'dashboard_personal.html', {
        'funcionario': funcionario,
        'todos_funcionarios': todos_funcionarios,
        'metricas': metricas,
        'actividades': actividades,
        'items_funcionario': items_funcionario,
        'areas_apoyo': areas_apoyo,
        'territorios': [
            'Sector Centro', 'El Milagro', 'La Pampa', 'Las Compañías',
            'La Antena', 'Avenida del Mar', 'Sector Rural', 'Otro',
        ],
        'periodo': periodo,
        'periodo_configurado': periodo_configurado,
        'metas_configuradas': bool(items_funcionario),
        'hoy': timezone.localdate(),
    })

def web_registrar_solicitante(request):
    if not request.user.is_authenticated:
        messages.error(request, 'Debe iniciar sesión para registrar solicitantes.')
        return redirect('web_login')

    form = SolicitanteForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                solicitante = form.save()
        except IntegrityError:
            if Solicitante.objects.filter(run=form.cleaned_data['run']).exists():
                form.add_error('run', 'Ya existe un solicitante registrado con ese RUN.')
            else:
                raise
        else:
            messages.success(request, 'Solicitante registrado correctamente.')
            return redirect(f"{reverse('web_registrar_actividad_diaria')}?solicitante_id={solicitante.id}")

    return render(request, 'registrar_solicitante.html', {
        'form': form,
        'form_data': request.POST if request.method == 'POST' else {},
        'tipo_solicitante_choices': Solicitante.TIPO_SOLICITANTE_CHOICES,
    })

def web_mi_ficha(request):
    if not request.user.is_authenticated:
        messages.error(request, 'Inicia sesión para editar tu ficha personal.')
        return redirect('web_login')

    if request.method == 'POST':
        form = MiFichaPersonalForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Tus datos personales se actualizaron correctamente.')
            return redirect('web_mi_ficha')
    else:
        form = MiFichaPersonalForm(instance=request.user, initial={
            'email_confirmacion': request.user.email,
        })

    return render(request, 'mi_ficha.html', {'form': form})

def _actividad_error(request, funcionario_id, error_code):
    campos_formulario = (
        'fecha_actividad', 'item_medicion_id', 'solicitante_id', 'direccion', 'solicitud_problema',
        'accion_ejecutada', 'compromiso_fecha',
        'compromiso_territorio', 'compromiso_area_apoyo', 'compromiso_descripcion',
        'latitud', 'longitud',
    )
    request.session['activity_form_data'] = {
        field: request.POST.get(field, '').strip()
        for field in campos_formulario
    }
    return redirect(f"{reverse('web_registrar_actividad_diaria')}?funcionario_id={funcionario_id}&activity_error={error_code}")

def _fecha_en_periodo(fecha, periodo):
    return bool(periodo and periodo.fecha_inicio <= fecha <= periodo.fecha_termino)

def _validar_fotos(fotos):
    if any(not foto.content_type or not foto.content_type.startswith('image/') for foto in fotos):
        raise ValidationError('Solo se permiten archivos de imagen como evidencia.')

def _guardar_fotos(actividad, fotos):
    _validar_fotos(fotos)
    evidencias = []
    for foto in fotos:
        evidencias.append(Evidencia.objects.create(
            actividad=actividad,
            archivo_foto=foto,
            estado=Evidencia.Estado.PENDIENTE,
            fecha_evidencia=timezone.localdate(),
        ))
    return evidencias

def web_registrar_actividad_personal(request):
    if not request.user.is_authenticated:
        messages.error(request, "Debe iniciar sesión para registrar actividades.")
        return redirect('web_login')

    periodo = get_periodo_activo()
    if request.method == 'GET':
        funcionario_id = request.GET.get('funcionario_id', '')
        if request.user.rol == Usuario.Rol.FUNCIONARIO:
            funcionario = request.user
        else:
            funcionario = Usuario.objects.filter(
                id=int(funcionario_id), rol=Usuario.Rol.FUNCIONARIO, is_active=True
            ).first() if funcionario_id.isdigit() else Usuario.objects.filter(
                rol=Usuario.Rol.FUNCIONARIO, is_active=True
            ).first()
        activity_error = request.GET.get('activity_error', '')
        activity_form_data = request.session.pop('activity_form_data', {}) if activity_error else {}
        if activity_form_data:
            saved_requester_id = activity_form_data.get('solicitante_id', '')
            selected_requester = Solicitante.objects.filter(
                id=int(saved_requester_id)
            ).first() if str(saved_requester_id).isdigit() else None
        else:
            requester_id = request.GET.get('solicitante_id', '')
            selected_requester = Solicitante.objects.filter(id=int(requester_id)).first() if requester_id.isdigit() else None
        return render(request, 'registrar_actividad.html', {
            'funcionario': funcionario,
            'funcionarios': Usuario.objects.filter(rol=Usuario.Rol.FUNCIONARIO, is_active=True).order_by('last_name', 'first_name'),
            'items_funcionario': ItemMedicion.objects.filter(periodo=periodo, activo=True, cargo=funcionario.cargo) if periodo and funcionario else [],
            'solicitantes': Solicitante.objects.order_by('nombre', 'apellido_paterno', 'apellido_materno'),
            'selected_requester': selected_requester,
            'activity_form_data': activity_form_data,
            'activity_error': {
                'fecha_futura': 'La fecha de la actividad no puede ser posterior a hoy.',
                'fecha_invalida': 'La fecha de la actividad no es válida.',
                'solicitante': 'Selecciona un solicitante registrado.',
                'item_invalido': 'Selecciona un ítem válido para el período y cargo.',
                'sin_periodo': 'No existe un período de medición activo para validar el compromiso.',
                'fecha_compromiso': 'La fecha del compromiso debe estar dentro del trimestre y no ser anterior a la actividad.',
                'actividad': 'Completa la dirección, el problema detectado y la acción realizada.',
                'ubicacion_invalida': 'La ubicación debe incluir coordenadas válidas de latitud y longitud.',
                'compromiso_datos': 'Selecciona un territorio y área válidos y completa la descripción del compromiso.',
                'datos_invalidos': 'No se pudo registrar la actividad. Revisa los datos y las imágenes adjuntas.',
            }.get(activity_error, ''),
            'periodo': periodo,
            'hoy': timezone.localdate(),
            'territorios': ACTIVIDAD_TERRITORIOS,
            'areas_apoyo': ACTIVIDAD_AREAS_APOYO,
        })

    if request.method == 'POST':
        funcionario_id = request.POST.get('funcionario_id')
        if request.user.rol == Usuario.Rol.FUNCIONARIO:
            funcionario = request.user
        elif funcionario_id and funcionario_id.isdigit():
            funcionario = get_object_or_404(
                Usuario, id=int(funcionario_id), rol=Usuario.Rol.FUNCIONARIO, is_active=True
            )
        else:
            messages.error(request, 'Selecciona un funcionario responsable.')
            return redirect('web_registrar_actividad_diaria')

        hoy = timezone.localdate()
        try:
            fecha_actividad = datetime.strptime(request.POST.get('fecha_actividad') or '', '%Y-%m-%d').date()
        except ValueError:
            return _actividad_error(request, funcionario.id, 'fecha_invalida')
        if fecha_actividad > hoy:
            return _actividad_error(request, funcionario.id, 'fecha_futura')

        periodo = get_periodo_activo()
        item_id = request.POST.get('item_medicion_id')
        items_disponibles = ItemMedicion.objects.filter(
            activo=True, periodo=periodo, cargo=funcionario.cargo
        ) if periodo and funcionario.cargo_id else ItemMedicion.objects.none()
        item_medicion = None
        if item_id:
            item_medicion = ItemMedicion.objects.filter(
                id=int(item_id), activo=True, periodo=periodo, cargo=funcionario.cargo
            ).first() if item_id.isdigit() else None
            if not item_medicion:
                return _actividad_error(request, funcionario.id, 'item_invalido')
        elif items_disponibles.exists():
            return _actividad_error(request, funcionario.id, 'item_invalido')

        solicitante_id = request.POST.get('solicitante_id', '')
        solicitante = Solicitante.objects.filter(id=int(solicitante_id)).first() if solicitante_id.isdigit() else None
        if not solicitante:
            return _actividad_error(request, funcionario.id, 'solicitante')
        telefono = solicitante.telefono or ''

        if not periodo:
            return _actividad_error(request, funcionario.id, 'sin_periodo')
        try:
            comp_fecha = datetime.strptime(request.POST.get('compromiso_fecha') or '', '%Y-%m-%d').date()
        except ValueError:
            return _actividad_error(request, funcionario.id, 'fecha_compromiso')
        if not _fecha_en_periodo(comp_fecha, periodo) or comp_fecha < fecha_actividad:
            return _actividad_error(request, funcionario.id, 'fecha_compromiso')
        territorio = (request.POST.get('compromiso_territorio') or '').strip()
        area_apoyo = (request.POST.get('compromiso_area_apoyo') or '').strip()
        compromiso_descripcion = (request.POST.get('compromiso_descripcion') or '').strip()
        if (
            territorio not in ACTIVIDAD_TERRITORIOS
            or area_apoyo not in ACTIVIDAD_AREAS_APOYO
            or not compromiso_descripcion
        ):
            return _actividad_error(request, funcionario.id, 'compromiso_datos')

        fotos = request.FILES.getlist('fotos')
        direccion = (request.POST.get('direccion') or '').strip()
        solicitud_problema = (request.POST.get('solicitud_problema') or '').strip()
        accion_ejecutada = (request.POST.get('accion_ejecutada') or '').strip()
        if not direccion or not solicitud_problema or not accion_ejecutada:
            return _actividad_error(request, funcionario.id, 'actividad')

        latitud_texto = (request.POST.get('latitud') or '').strip()
        longitud_texto = (request.POST.get('longitud') or '').strip()
        latitud = longitud = None
        if latitud_texto or longitud_texto:
            try:
                latitud = float(latitud_texto)
                longitud = float(longitud_texto)
            except ValueError:
                return _actividad_error(request, funcionario.id, 'ubicacion_invalida')
            if not (-90 <= latitud <= 90 and -180 <= longitud <= 180):
                return _actividad_error(request, funcionario.id, 'ubicacion_invalida')

        delegacion = funcionario.delegacion or Delegacion.objects.first()
        if not delegacion:
            messages.error(request, 'El funcionario no tiene una delegación asignada.')
            return redirect(f"{reverse('web_personal')}?id={funcionario.id}")

        try:
            with transaction.atomic():
                actividad = Actividad.objects.create(
                    funcionario=funcionario,
                    delegacion=delegacion,
                    solicitante=solicitante,
                    item_medicion=item_medicion,
                    fecha_actividad=fecha_actividad,
                    contacto_nombre=str(solicitante),
                    contacto_telefono=telefono,
                    solicitud_problema=solicitud_problema,
                    actividad_solicitud=solicitud_problema,
                    accion=accion_ejecutada,
                    accion_ejecutada=accion_ejecutada,
                    direccion=direccion,
                    latitud=latitud,
                    longitud=longitud,
                )
                evidencias = _guardar_fotos(actividad, fotos)
                compromiso = CompromisoAgenda.objects.create(
                    solicitante=str(solicitante),
                    origen='EXT',
                    territorio=territorio,
                    delegacion=delegacion,
                    responsable=funcionario,
                    fecha_compromiso=comp_fecha,
                    fecha_comprometida=comp_fecha,
                    area_apoyo=area_apoyo,
                    descripcion=compromiso_descripcion,
                    observacion='Compromiso generado desde el registro de actividad.',
                    observaciones='Compromiso generado desde el registro de actividad.',
                    estado=CompromisoAgenda.Estado.EN_PROCESO,
                    actividad=actividad,
                    creado_por=request.user,
                )
                actividad.compromiso_agenda = compromiso
                actividad.save(update_fields=['compromiso_agenda'])

                RegistroAuditoria.objects.create(
                    usuario=request.user,
                    accion='REGISTRO_TODO_EN_UNO',
                    entidad='Actividad',
                    identificador_registro=str(actividad.id),
                    valor_nuevo={
                        'actividad_id': actividad.id,
                        'funcionario': funcionario.username,
                        'evidencias': [e.codigo_verificador for e in evidencias],
                        'compromiso_id': compromiso.id if compromiso else None,
                    },
                    ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1'),
                )
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
            return _actividad_error(request, funcionario.id, 'datos_invalidos')

        msg_exito = f"Actividad #{actividad.id} registrada correctamente."
        if evidencias:
            msg_exito += f" Se adjuntaron {len(evidencias)} evidencia(s) para revisión."
        msg_exito += f" Se vinculó el compromiso #{compromiso.id} al Tubo de Trabajo."
        messages.success(request, msg_exito)
        return redirect(f"{reverse('web_personal')}?id={funcionario.id}")

    return redirect('web_registrar_actividad_diaria')

def web_agregar_evidencia(request, actividad_id):
    if not request.user.is_authenticated:
        messages.error(request, 'Debe iniciar sesión para agregar evidencias.')
        return redirect('web_login')
    actividad = get_object_or_404(
        Actividad.objects.select_related('funcionario', 'delegacion'), id=actividad_id
    )
    if request.user.rol == Usuario.Rol.FUNCIONARIO and actividad.funcionario_id != request.user.id:
        messages.error(request, 'Solo puedes agregar evidencias a tus propias actividades.')
        return redirect('web_personal')
    if request.user.rol == Usuario.Rol.DELEGADO and actividad.delegacion_id != request.user.delegacion_id:
        messages.error(request, 'Solo puedes agregar evidencias a actividades de tu delegación.')
        return redirect('web_personal')
    if request.method != 'POST':
        return redirect(f"{reverse('web_personal')}?id={actividad.funcionario_id}")
    fotos = request.FILES.getlist('fotos')
    if not fotos:
        messages.error(request, 'Selecciona al menos una fotografía para agregar evidencia.')
        return redirect(f"{reverse('web_personal')}?id={actividad.funcionario_id}")
    try:
        with transaction.atomic():
            evidencias = _guardar_fotos(actividad, fotos)
            RegistroAuditoria.objects.create(
                usuario=request.user,
                accion='AGREGAR_EVIDENCIA',
                entidad='Actividad',
                identificador_registro=str(actividad.id),
                valor_nuevo={'evidencias': [e.codigo_verificador for e in evidencias]},
                ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1'),
            )
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
        return redirect(f"{reverse('web_personal')}?id={actividad.funcionario_id}")
    messages.success(request, f'Se agregaron {len(evidencias)} evidencia(s) a la actividad #{actividad.id}.')
    return redirect(f"{reverse('web_personal')}?id={actividad.funcionario_id}")

def web_verificacion(request):
    if not request.user.is_authenticated:
        return redirect('web_login')

    if request.user.rol == Usuario.Rol.FUNCIONARIO:
        messages.warning(request, "Acceso restringido: La bandeja de Validación 'Check' está reservada para Delegados Municipales y Jefaturas (Segregación de Funciones RN-009).")
        return redirect('web_personal')

    delegaciones = Delegacion.objects.filter(activo=True)
    delegacion_filtro = request.GET.get('delegacion_id')
    estado_filtro = request.GET.get('estado', 'PENDIENTE')

    evidencias = Evidencia.objects.all()
    if request.user.rol == Usuario.Rol.DELEGADO:
        if request.user.delegacion_id:
            evidencias = evidencias.filter(actividad__delegacion_id=request.user.delegacion_id)
        else:
            evidencias = evidencias.none()
    evidencias = evidencias.select_related(
        'actividad__delegacion', 'actividad__funcionario', 'verificador'
    ).order_by('-fecha_subida')

    if delegacion_filtro:
        try:
            evidencias = evidencias.filter(actividad__delegacion_id=int(delegacion_filtro))
        except ValueError:
            pass

    if estado_filtro and estado_filtro != 'TODOS':
        evidencias = evidencias.filter(estado=estado_filtro)

    return render(request, 'verificacion_check.html', {
        'evidencias': evidencias,
        'delegaciones': delegaciones,
        'delegacion_filtro': int(delegacion_filtro) if delegacion_filtro else None,
        'estado_filtro': estado_filtro,
    })

def web_validar_evidencia(request, evidencia_id):
    if not request.user.is_authenticated or request.user.rol not in [Usuario.Rol.DELEGADO, Usuario.Rol.COORDINADOR, Usuario.Rol.ADMIN]:
        messages.error(request, "Acceso denegado: Un funcionario no puede auto-aprobar evidencias. Solo Delegados Municipales, Coordinadores y Administradores tienen facultades de validación (Regla RN-009 y Criterio CA-07).")
        return redirect('web_verificacion')

    if request.method == 'POST':
        evidencias = Evidencia.objects.all()
        if request.user.rol == Usuario.Rol.DELEGADO:
            if not request.user.delegacion_id:
                messages.error(request, 'Debes tener una delegación asignada para validar evidencias.')
                return redirect('web_verificacion')
            evidencias = evidencias.filter(actividad__delegacion_id=request.user.delegacion_id)
        evidencia = get_object_or_404(evidencias, id=evidencia_id)
        decision = request.POST.get('decision')
        observacion = request.POST.get('observacion', '')

        if decision in Evidencia.Estado.values:
            ant_est = evidencia.estado
            evidencia.estado = decision
            evidencia.observacion = observacion
            evidencia.verificador = request.user
            evidencia.fecha_validacion = timezone.now()
            evidencia.save()

            RegistroAuditoria.objects.create(
                usuario=request.user if request.user.is_authenticated else None,
                accion='VALIDAR_EVIDENCIA', entidad='Evidencia',
                identificador_registro=str(evidencia.id),
                valor_anterior={'estado': ant_est},
                valor_nuevo={'estado': decision, 'observacion': observacion, 'codigo': evidencia.codigo_verificador},
                ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1')
            )
            compromiso = evidencia.actividad.compromiso_agenda
            messages.success(request, f"Evidencia {evidencia.codigo_verificador} validada como {evidencia.get_estado_display()}.")

    return redirect('web_verificacion')

def web_tubo(request):
    delegaciones = Delegacion.objects.filter(activo=True)
    usuarios_terreno = Usuario.objects.filter(is_active=True).select_related('delegacion')
    hoy = timezone.now().date()

    compromisos = list(CompromisoAgenda.objects.all().select_related(
        'delegacion', 'responsable', 'creado_por', 'actividad'
    ).prefetch_related('actividad__evidencias').order_by('fecha_comprometida'))
    # Resumen colectivo por Colaborador (Slide 14 de la presentación municipal)
    resumen_colaboradores = []
    totales_colectivos = {
        'ingresado': 0,
        'pendiente': 0,
        'en_proceso': 0,
        'realizado': 0,
        'total': 0
    }

    resumen_por_usuario = {}
    for compromiso in compromisos:
        resumen = resumen_por_usuario.setdefault(compromiso.responsable_id, {
            'usuario': compromiso.responsable,
            'ingresado': 0, 'pendiente': 0, 'en_proceso': 0, 'realizado': 0, 'total': 0,
        })
        estado = compromiso.estado_tablero
        if estado == CompromisoAgenda.Estado.INGRESADO:
            resumen['ingresado'] += 1
        elif estado == CompromisoAgenda.Estado.PENDIENTE:
            resumen['pendiente'] += 1
        elif estado == CompromisoAgenda.Estado.EN_PROCESO:
            resumen['en_proceso'] += 1
        elif estado in [CompromisoAgenda.Estado.COMPLETADO, CompromisoAgenda.Estado.REALIZADO]:
            resumen['realizado'] += 1
        resumen['total'] += 1

    for resumen in resumen_por_usuario.values():
        u = resumen['usuario']
        pct = round((resumen['realizado'] / resumen['total']) * 100.0, 1) if resumen['total'] > 0 else 0.0
        cumple = (pct >= 80.0)
        resumen_colaboradores.append({
            'usuario': u,
            'nombre': u.get_full_name() or u.username,
            'delegacion': u.delegacion.codigo if u.delegacion else 'Central',
            'ingresado': resumen['ingresado'],
            'pendiente': resumen['pendiente'],
            'en_proceso': resumen['en_proceso'],
            'realizado': resumen['realizado'],
            'total': resumen['total'],
            'pct_realizado': pct,
            'cumple': cumple
        })
        for key in ['ingresado', 'pendiente', 'en_proceso', 'realizado', 'total']:
            totales_colectivos[key] += resumen[key]

    if totales_colectivos['total'] > 0:
        totales_colectivos['pct_realizado'] = round((totales_colectivos['realizado'] / totales_colectivos['total']) * 100.0, 1)
        totales_colectivos['cumple'] = (totales_colectivos['pct_realizado'] >= 80.0)
    else:
        totales_colectivos['pct_realizado'] = 0.0
        totales_colectivos['cumple'] = False

    return render(request, 'tubo_trabajo.html', {
        'delegaciones': delegaciones,
        'usuarios_terreno': usuarios_terreno,
        'hoy': hoy,
        'todos_los_compromisos': compromisos,
        'ingresados': [c for c in compromisos if c.estado_tablero == CompromisoAgenda.Estado.INGRESADO],
        'pendientes': [c for c in compromisos if c.estado_tablero == CompromisoAgenda.Estado.PENDIENTE],
        'en_proceso': [c for c in compromisos if c.estado_tablero == CompromisoAgenda.Estado.EN_PROCESO],
        'realizados': [c for c in compromisos if c.estado_tablero in [CompromisoAgenda.Estado.COMPLETADO, CompromisoAgenda.Estado.REALIZADO]],
        'vencidos': [c for c in compromisos if c.estado_tablero == CompromisoAgenda.Estado.VENCIDO],
        'reprogramados': [c for c in compromisos if c.estado_tablero == CompromisoAgenda.Estado.REPROGRAMADO],
        'periodo': get_periodo_activo(),
        'fecha_min_periodo': get_periodo_activo().fecha_inicio if get_periodo_activo() else hoy,
        'fecha_max_periodo': get_periodo_activo().fecha_termino if get_periodo_activo() else hoy,
        'actividades': Actividad.objects.select_related('funcionario', 'delegacion').order_by('-fecha_actividad')[:200],
        'territorios': [
            'Sector Centro', 'El Milagro', 'La Pampa', 'Las Compañías',
            'La Antena', 'Avenida del Mar', 'Sector Rural', 'Otro',
        ],
        'resumen_colaboradores': resumen_colaboradores,
        'totales_colectivos': totales_colectivos,
    })

def web_cambiar_estado_compromiso(request, compromiso_id):
    if not request.user.is_authenticated:
        messages.error(request, "Debe iniciar sesión para modificar el estado de un compromiso.")
        return redirect('web_login')

    if request.method == 'POST':
        compromiso = get_object_or_404(CompromisoAgenda, id=compromiso_id)
        if not _puede_gestionar_compromiso(request.user, compromiso):
            raise PermissionDenied
        nuevo_estado = request.POST.get('estado')
        estados_editables = [
            CompromisoAgenda.Estado.INGRESADO,
            CompromisoAgenda.Estado.PENDIENTE,
            CompromisoAgenda.Estado.EN_PROCESO,
            CompromisoAgenda.Estado.REPROGRAMADO,
        ]
        if nuevo_estado in estados_editables:
            ant = compromiso.estado
            compromiso.estado = nuevo_estado
            compromiso.save()
            RegistroAuditoria.objects.create(
                usuario=request.user,
                accion='CAMBIO_ESTADO', entidad='CompromisoAgenda',
                identificador_registro=str(compromiso.id),
                valor_anterior={'estado': ant},
                valor_nuevo={'estado': nuevo_estado},
                ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1')
            )
            messages.success(request, f"Compromiso #{compromiso.id} movido a {compromiso.get_estado_display()}.")
    return redirect('web_tubo')

def web_crear_compromiso(request):
    if not request.user.is_authenticated:
        messages.error(request, "Debe iniciar sesión para registrar nuevos compromisos.")
        return redirect('web_login')

    if request.method == 'POST':
        solicitante = (request.POST.get('solicitante') or '').strip() or 'Vecino La Serena'
        origen = request.POST.get('origen') or 'INT'
        territorio = (request.POST.get('territorio') or '').strip() or 'La Serena'
        delegacion_id = request.POST.get('delegacion_id') or request.user.delegacion_id
        if request.user.rol not in (Usuario.Rol.ADMIN, Usuario.Rol.COORDINADOR) and (
            not request.user.delegacion_id or str(delegacion_id) != str(request.user.delegacion_id)
        ):
            raise PermissionDenied
        responsable_id = request.POST.get('responsable_id') or request.user.id
        if request.user.rol == Usuario.Rol.FUNCIONARIO:
            responsable_id = request.user.id
        elif request.user.rol == Usuario.Rol.DELEGADO:
            responsable = get_object_or_404(Usuario, id=responsable_id)
            if responsable.delegacion_id != request.user.delegacion_id:
                raise PermissionDenied
        if request.user.rol not in (
            Usuario.Rol.ADMIN, Usuario.Rol.COORDINADOR, Usuario.Rol.DELEGADO, Usuario.Rol.FUNCIONARIO
        ) and not request.user.is_superuser:
            raise PermissionDenied
        periodo = get_periodo_activo()
        try:
            fecha_comp = datetime.strptime(request.POST.get('fecha_comprometida', ''), '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Ingresa una fecha de compromiso válida.')
            return redirect('web_tubo')
        if not _fecha_en_periodo(fecha_comp, periodo):
            messages.error(request, 'La fecha del compromiso debe estar dentro del período trimestral activo.')
            return redirect('web_tubo')
        area_apoyo = (request.POST.get('area_apoyo') or '').strip() or 'Operaciones y Territorio'
        descripcion = (request.POST.get('descripcion') or '').strip() or 'Compromiso vecinal registrado en terreno'
        observaciones = (request.POST.get('observaciones') or '').strip()
        estado = request.POST.get('estado') or CompromisoAgenda.Estado.PENDIENTE

        c = CompromisoAgenda.objects.create(
            solicitante=solicitante,
            origen=origen,
            territorio=territorio,
            delegacion_id=delegacion_id,
            responsable_id=responsable_id,
            fecha_compromiso=fecha_comp,
            fecha_comprometida=fecha_comp,
            area_apoyo=area_apoyo,
            descripcion=descripcion,
            observacion=observaciones,
            estado=estado if estado in [
                CompromisoAgenda.Estado.INGRESADO, CompromisoAgenda.Estado.PENDIENTE,
                CompromisoAgenda.Estado.EN_PROCESO,
            ] else CompromisoAgenda.Estado.PENDIENTE,
            creado_por=request.user
        )
        RegistroAuditoria.objects.create(
            usuario=request.user,
            accion='CREAR', entidad='CompromisoAgenda',
            identificador_registro=str(c.id),
            valor_nuevo={'solicitante': c.solicitante, 'responsable': c.responsable.username, 'fecha': str(c.fecha_comprometida)},
            ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1')
        )
        messages.success(request, f"Nuevo compromiso #{c.id} guardado exitosamente en el Tubo de Trabajo.")
    return redirect('web_tubo')

def web_editar_compromiso(request, compromiso_id):
    if not request.user.is_authenticated:
        messages.error(request, "Debe iniciar sesión para modificar compromisos.")
        return redirect('web_login')

    compromiso = get_object_or_404(CompromisoAgenda, id=compromiso_id)
    if not _puede_gestionar_compromiso(request.user, compromiso):
        raise PermissionDenied

    if request.method == 'POST':
        solicitante = (request.POST.get('solicitante') or '').strip()
        territorio = (request.POST.get('territorio') or '').strip()
        delegacion_id = request.POST.get('delegacion_id')
        responsable_id = request.POST.get('responsable_id')
        fecha_comp_str = request.POST.get('fecha_comprometida')
        area_apoyo = (request.POST.get('area_apoyo') or '').strip()
        descripcion = (request.POST.get('descripcion') or '').strip()
        observaciones = (request.POST.get('observaciones') or '').strip()
        estado = request.POST.get('estado')
        delegacion = compromiso.delegacion
        responsable = compromiso.responsable
        if delegacion_id:
            delegacion = get_object_or_404(Delegacion, id=delegacion_id)
        if responsable_id:
            responsable = get_object_or_404(Usuario, id=responsable_id)
        if request.user.rol not in (Usuario.Rol.ADMIN, Usuario.Rol.COORDINADOR):
            if delegacion.pk != request.user.delegacion_id:
                raise PermissionDenied
            if request.user.rol == Usuario.Rol.FUNCIONARIO and responsable.pk != request.user.pk:
                raise PermissionDenied
            if request.user.rol == Usuario.Rol.DELEGADO and responsable.delegacion_id != request.user.delegacion_id:
                raise PermissionDenied

        fecha_comp = None
        if fecha_comp_str:
            try:
                fecha_comp = datetime.strptime(fecha_comp_str, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Ingresa una fecha de compromiso válida.')
                return redirect('web_tubo')
            if not _fecha_en_periodo(fecha_comp, get_periodo_activo()):
                messages.error(request, 'La fecha del compromiso debe estar dentro del período trimestral activo.')
                return redirect('web_tubo')

        foto_files = request.FILES.getlist('fotos')
        actividad_id = request.POST.get('actividad_id')
        actividad_nueva = compromiso.actividad if not actividad_id else get_object_or_404(Actividad, id=actividad_id)
        if actividad_nueva:
            if actividad_nueva.delegacion_id != delegacion.id:
                messages.error(request, 'La actividad seleccionada debe pertenecer a la misma delegación del compromiso.')
                return redirect('web_tubo')
            if (
                actividad_nueva.compromiso_agenda_id not in (None, compromiso.id)
                or actividad_nueva.compromisos.exclude(pk=compromiso.id).exists()
            ):
                messages.error(request, 'La actividad ya está vinculada a otro compromiso.')
                return redirect('web_tubo')
        if foto_files and not actividad_nueva:
            messages.error(request, 'Selecciona una actividad asociada antes de cargar evidencias.')
            return redirect('web_tubo')
        if fecha_comp and actividad_nueva and fecha_comp < actividad_nueva.fecha_actividad:
            messages.error(request, 'La fecha comprometida no puede ser anterior a la fecha de la actividad.')
            return redirect('web_tubo')
        try:
            if foto_files:
                _validar_fotos(foto_files)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
            return redirect('web_tubo')

        ant_data = {
            'solicitante': compromiso.solicitante,
            'estado': compromiso.estado,
            'fecha_comprometida': str(compromiso.fecha_comprometida),
            'responsable': compromiso.responsable.username if compromiso.responsable else ''
        }

        actividad_anterior = compromiso.actividad
        with transaction.atomic():
            if solicitante:
                compromiso.solicitante = solicitante
            if territorio:
                compromiso.territorio = territorio
            compromiso.delegacion = delegacion
            compromiso.responsable = responsable
            if fecha_comp:
                compromiso.fecha_comprometida = fecha_comp
                compromiso.fecha_compromiso = fecha_comp
            if area_apoyo:
                compromiso.area_apoyo = area_apoyo
            if descripcion:
                compromiso.descripcion = descripcion
            if observaciones:
                compromiso.observacion = observaciones
                compromiso.observaciones = observaciones
            if estado in [
                CompromisoAgenda.Estado.INGRESADO, CompromisoAgenda.Estado.PENDIENTE,
                CompromisoAgenda.Estado.EN_PROCESO, CompromisoAgenda.Estado.REPROGRAMADO,
            ]:
                compromiso.estado = estado
            compromiso.actividad = actividad_nueva
            compromiso.save()

            if actividad_anterior and actividad_anterior != actividad_nueva:
                if actividad_anterior.compromiso_agenda_id == compromiso.id:
                    actividad_anterior.compromiso_agenda = None
                    actividad_anterior.save(update_fields=['compromiso_agenda', 'actualizado_en'])
            if actividad_nueva and actividad_nueva.compromiso_agenda_id != compromiso.id:
                actividad_nueva.compromiso_agenda = compromiso
                actividad_nueva.save(update_fields=['compromiso_agenda', 'actualizado_en'])

            if foto_files:
                if request.POST.get('reemplazar_fotos') == 'on':
                    primera_evidencia = actividad_nueva.evidencias.first()
                    if primera_evidencia:
                        primera_evidencia.archivo_foto = foto_files[0]
                        primera_evidencia.archivo_foto_2 = None
                        primera_evidencia.archivo_foto_3 = None
                        primera_evidencia.url_foto_simulada = ''
                        primera_evidencia.url_foto_simulada_2 = ''
                        primera_evidencia.url_foto_simulada_3 = ''
                        primera_evidencia.estado = Evidencia.Estado.PENDIENTE
                        primera_evidencia.fecha_validacion = None
                        primera_evidencia.verificador = None
                        primera_evidencia.fecha_evidencia = timezone.localdate()
                        primera_evidencia.save()
                        _guardar_fotos(actividad_nueva, foto_files[1:])
                    else:
                        _guardar_fotos(actividad_nueva, foto_files)
                else:
                    _guardar_fotos(actividad_nueva, foto_files)

            if compromiso.actividad_id:
                compromiso.sincronizar_estado_evidencias()

            RegistroAuditoria.objects.create(
                usuario=request.user,
                accion='EDITAR_COMPROMISO',
                entidad='CompromisoAgenda',
                identificador_registro=str(compromiso.id),
                valor_anterior=ant_data,
                valor_nuevo={
                    'solicitante': compromiso.solicitante,
                    'estado': compromiso.estado,
                    'fecha': str(compromiso.fecha_comprometida),
                    'actividad_id': compromiso.actividad_id,
                },
                ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1')
            )
        messages.success(request, f"Compromiso #{compromiso.id} actualizado exitosamente.")
    return redirect('web_tubo')

def web_eliminar_compromiso(request, compromiso_id):
    if not request.user.is_authenticated:
        messages.error(request, "Debe iniciar sesión para eliminar compromisos.")
        return redirect('web_login')

    compromiso = get_object_or_404(CompromisoAgenda, id=compromiso_id)
    if not _puede_gestionar_compromiso(request.user, compromiso):
        raise PermissionDenied

    if request.method == 'POST':
        c_id = compromiso.id
        solic = compromiso.solicitante
        with transaction.atomic():
            actividad = compromiso.actividad
            if actividad and actividad.compromisos.count() == 1:
                actividad.delete()
            else:
                compromiso.delete()
            RegistroAuditoria.objects.create(
                usuario=request.user,
                accion='ELIMINAR_COMPROMISO',
                entidad='CompromisoAgenda',
                identificador_registro=str(c_id),
                valor_anterior={'solicitante': solic},
                valor_nuevo=None,
                ip_origen=request.META.get('REMOTE_ADDR', '127.0.0.1')
            )
        messages.success(request, f"Compromiso #{c_id} de '{solic}' eliminado del Tubo de Trabajo.")
    return redirect('web_tubo')

def web_terreno(request):
    if not request.user.is_authenticated:
        return redirect('web_login')

    periodo = get_periodo_activo()
    items_medicion = ItemMedicion.objects.filter(
        periodo=periodo, activo=True, cargo=request.user.cargo
    ) if periodo and request.user.cargo_id else []
    actividades = Actividad.objects.select_related(
        'delegacion', 'funcionario', 'item', 'item_medicion'
    ).order_by('-fecha_actividad')
    if request.user.rol == Usuario.Rol.FUNCIONARIO:
        actividades = actividades.filter(funcionario=request.user)
    elif request.user.delegacion_id:
        actividades = actividades.filter(delegacion_id=request.user.delegacion_id)

    if request.method == 'POST':
        actividad_id = request.POST.get('actividad_id')
        if actividad_id:
            actividad = get_object_or_404(actividades, id=actividad_id)
            fotos = request.FILES.getlist('fotos')
            if not fotos:
                messages.error(request, 'Selecciona al menos una fotografía para adjuntarla a la actividad.')
                return redirect('web_terreno')
            try:
                with transaction.atomic():
                    evidencias = _guardar_fotos(actividad, fotos)
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
                return redirect('web_terreno')
            messages.success(request, f'Se agregaron {len(evidencias)} evidencia(s) a la actividad #{actividad.id}.')
            return redirect('web_personal')

        direccion = (request.POST.get('direccion') or '').strip()
        accion = (request.POST.get('accion_ejecutada') or '').strip()
        fotos = request.FILES.getlist('fotos')
        if not direccion or not accion or not fotos:
            messages.error(request, 'Para crear una actividad nueva completa la dirección, la acción y adjunta al menos una foto.')
            return redirect('web_terreno')
        item_id = request.POST.get('item_medicion')
        item = ItemMedicion.objects.filter(
            id=item_id, periodo=periodo, cargo=request.user.cargo, activo=True
        ).first() if item_id and periodo else None
        if item_id and not item:
            messages.error(request, 'El ítem seleccionado no corresponde al período o cargo actual.')
            return redirect('web_terreno')
        try:
            latitud = float(request.POST.get('latitud', ''))
            longitud = float(request.POST.get('longitud', ''))
        except (TypeError, ValueError):
            latitud = longitud = None
        delegacion = request.user.delegacion or Delegacion.objects.first()
        if not delegacion:
            messages.error(request, 'No hay una delegación configurada para registrar la actividad.')
            return redirect('web_terreno')
        try:
            with transaction.atomic():
                actividad = Actividad.objects.create(
                    funcionario=request.user,
                    delegacion=delegacion,
                    item_medicion=item,
                    fecha_actividad=timezone.localdate(),
                    direccion=direccion,
                    latitud=latitud,
                    longitud=longitud,
                    actividad_solicitud=f'Actividad en terreno: {direccion}',
                    solicitud_problema=f'Actividad en terreno: {direccion}',
                    accion_ejecutada=accion,
                    accion=accion,
                )
                _guardar_fotos(actividad, fotos)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
            return redirect('web_terreno')
        messages.success(request, f'Actividad #{actividad.id} registrada con {len(fotos)} evidencia(s).')
        return redirect('web_personal')

    return render(request, 'terreno_movil.html', {
        'items_medicion': items_medicion,
        'actividades_existentes': actividades[:200],
    })

def web_casos_sociales(request):
    casos = CasoSocial.objects.all()
    if not request.user.is_superuser and request.user.rol not in (
        Usuario.Rol.ADMIN,
        Usuario.Rol.COORDINADOR,
    ):
        if request.user.rol == Usuario.Rol.DELEGADO and request.user.delegacion_id:
            casos = casos.filter(delegacion_id=request.user.delegacion_id)
        else:
            casos = casos.none()

    casos = casos.prefetch_related('atenciones').select_related('delegacion')
    return render(request, 'casos_sociales.html', {
        'casos': casos,
    })

def web_auditoria(request):
    if not request.user.is_authenticated or request.user.rol not in [Usuario.Rol.ADMIN, Usuario.Rol.COORDINADOR]:
        messages.warning(request, "Acceso restringido: El registro inmutable de auditoría está reservado para la Coordinación Comunal y Administradores (Seguridad RNF-008).")
        return redirect('web_dashboard')

    registros = RegistroAuditoria.objects.all().select_related('usuario')[:50]
    return render(request, 'auditoria.html', {
        'registros': registros,
    })

def api_geocodificar_direccion(request):
    import urllib.request, urllib.parse, json, re
    from urllib.error import URLError
    from django.http import JsonResponse

    latitud = request.GET.get('lat')
    longitud = request.GET.get('lng')
    if latitud is not None or longitud is not None:
        try:
            lat = float(latitud)
            lng = float(longitud)
        except (TypeError, ValueError):
            return JsonResponse({'encontrado': False, 'error': 'Coordenadas inválidas'}, status=400)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return JsonResponse({'encontrado': False, 'error': 'Coordenadas fuera de rango'}, status=400)

        url = (
            'https://nominatim.openstreetmap.org/reverse?format=jsonv2'
            f'&lat={lat}&lon={lng}&zoom=18&addressdetails=1'
        )
        headers = {'User-Agent': 'MatrizSGR-MunicipalidadLaSerena/1.0 (contacto@laserena.cl)'}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except (URLError, TimeoutError, json.JSONDecodeError):
            return JsonResponse(
                {'encontrado': False, 'error': 'No fue posible consultar la dirección cercana'},
                status=502,
            )

        if not isinstance(data, dict):
            return JsonResponse(
                {'encontrado': False, 'error': 'La respuesta de direcciones no es válida'},
                status=502,
            )
        address = data.get('address')
        if not isinstance(address, dict):
            address = {}
        calle = address.get('road') or address.get('pedestrian') or address.get('residential')
        numero = address.get('house_number')
        localidad = (
            address.get('city')
            or address.get('town')
            or address.get('village')
            or address.get('municipality')
        )
        sector = address.get('suburb') or address.get('neighbourhood')
        partes = []
        if calle:
            partes.append(f'{calle} {numero}' if numero else calle)
        if sector and sector.lower() not in (calle or '').lower():
            partes.append(sector)
        if localidad and localidad.lower() not in ' '.join(partes).lower():
            partes.append(localidad)
        direccion = ', '.join(partes) or data.get('display_name')
        if not direccion:
            return JsonResponse(
                {'encontrado': False, 'error': 'No se encontró una dirección cercana'},
                status=200,
            )
        return JsonResponse({
            'encontrado': True,
            'direccion_encontrada': direccion,
            'numero_encontrado': bool(numero),
            'aproximada': True,
            'lat': lat,
            'lng': lng,
        })

    query = (request.GET.get('q') or '').strip()
    if not query:
        return JsonResponse({'encontrado': False, 'error': 'Dirección no provista'}, status=400)

    headers = {'User-Agent': 'MatrizSGR-MunicipalidadLaSerena/1.0 (contacto@laserena.cl)'}
    clean_no_digits = re.sub(r'\d+', '', query).strip()

    attempts = [
        f'{query}, La Serena, Chile',
        f'{query}, Región de Coquimbo, Chile',
        f'{query}, Chile',
    ]
    if clean_no_digits and clean_no_digits != query:
        attempts.extend([
            f'{clean_no_digits}, La Serena, Chile',
            f'{clean_no_digits}, Región de Coquimbo, Chile',
            f'{clean_no_digits}, Chile',
        ])

    for q_att in attempts:
        url = f'https://nominatim.openstreetmap.org/search?format=json&limit=1&q={urllib.parse.quote(q_att)}'
        try:
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=3)
            data = json.loads(resp.read().decode('utf-8'))
            if data and len(data) > 0:
                lat = float(data[0]['lat'])
                lng = float(data[0]['lon'])
                display_name = data[0].get('display_name', query)
                return JsonResponse({
                    'encontrado': True,
                    'lat': lat,
                    'lng': lng,
                    'direccion_encontrada': display_name
                })
        except Exception:
            continue

    return JsonResponse({'encontrado': False, 'error': 'No se encontraron coordenadas exactas'}, status=200)
