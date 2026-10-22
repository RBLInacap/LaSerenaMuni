from datetime import date, timedelta
import json
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from sgr_app.models import (
    Actividad,
    Cargo,
    CompromisoAgenda,
    Delegacion,
    Evidencia,
    ItemMedicion,
    PeriodoMedicion,
    Solicitante,
    Usuario,
)
from sgr_app.serializers import (
    ActividadSerializer,
    AtencionSocialSerializer,
    CasoSocialSerializer,
    UsuarioSerializer,
)
from sgr_app.periodos import get_nombre_trimestre_actual, get_periodo_trimestre_actual
from sgr_app.validators import (
    normalize_chilean_phone,
    normalize_chilean_rut,
    validate_chilean_rut,
)
class ActivityWorkflowTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        quarter_month = ((self.today.month - 1) // 3) * 3 + 1
        self.period_start = date(self.today.year, quarter_month, 1)
        next_quarter_month = quarter_month + 3
        if next_quarter_month == 13:
            next_quarter_month = 1
            next_quarter_year = self.today.year + 1
        else:
            next_quarter_year = self.today.year
        next_quarter_start = date(next_quarter_year, next_quarter_month, 1)
        self.period_end = next_quarter_start - timedelta(days=1)

        self.delegacion = Delegacion.objects.create(nombre='Delegación de prueba', codigo='TST')
        self.cargo = Cargo.objects.create(nombre='Gestor de prueba')
        self.funcionario = Usuario.objects.create_user(
            username='funcionario.workflow',
            password='TestPassword123!',
            rol=Usuario.Rol.FUNCIONARIO,
            cargo=self.cargo,
            delegacion=self.delegacion,
        )
        self.periodo = PeriodoMedicion.objects.create(
            nombre='Período de prueba',
            fecha_inicio=self.period_start,
            fecha_termino=self.period_end,
        )
        self.item = ItemMedicion.objects.create(
            cargo=self.cargo,
            periodo=self.periodo,
            nombre_item='Actividad de prueba',
            meta_cuantitativa=10,
            ponderador=100,
        )
        self.solicitante = Solicitante.objects.create(
            run='11.111.111-1',
            nombre='Andrea',
            apellido='Prueba Ejemplo',
            apellido_paterno='Prueba',
            apellido_materno='Ejemplo',
            tipo_solicitante='VECINO',
            correo='andrea@example.com',
            telefono='+56 9 1234 5678',
        )
        self.client = Client()
        self.client.force_login(self.funcionario)
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)

    def upload(self, name):
        return SimpleUploadedFile(name, b'test-image', content_type='image/jpeg')

    def profile_form(self, **overrides):
        data = {
            'first_name': 'Andrea',
            'last_name': 'Funcionaria Prueba',
            'email': 'andrea.funcionaria@example.com',
            'email_confirmacion': 'andrea.funcionaria@example.com',
            'telefono': '9 8765 4321',
            'password_actual': '',
            'password_nueva': '',
            'password_confirmacion': '',
        }
        data.update(overrides)
        return data

    def test_personal_profile_can_update_contact_details(self):
        response = self.client.post('/mi-ficha/', self.profile_form())

        self.assertRedirects(response, '/mi-ficha/')
        self.funcionario.refresh_from_db()
        self.assertEqual(self.funcionario.first_name, 'Andrea')
        self.assertEqual(self.funcionario.last_name, 'Funcionaria Prueba')
        self.assertEqual(self.funcionario.email, 'andrea.funcionaria@example.com')
        self.assertEqual(self.funcionario.telefono, '+56987654321')
        self.assertTrue(self.funcionario.check_password('TestPassword123!'))

    def test_personal_profile_requires_matching_email_confirmation(self):
        response = self.client.post(
            '/mi-ficha/',
            self.profile_form(email_confirmacion='otro@example.com'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Los correos electrónicos no coinciden.')
        self.funcionario.refresh_from_db()
        self.assertEqual(self.funcionario.email, '')

    def test_personal_profile_rejects_email_already_used_by_another_account(self):
        Usuario.objects.create_user(
            username='otra.cuenta',
            password='TestPassword123!',
            email='ocupado@example.com',
        )
        response = self.client.post(
            '/mi-ficha/',
            self.profile_form(
                email='ocupado@example.com',
                email_confirmacion='ocupado@example.com',
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Este correo electrónico ya está asociado a otra cuenta.')
        self.funcionario.refresh_from_db()
        self.assertEqual(self.funcionario.email, '')

    def test_personal_profile_requires_valid_chilean_phone(self):
        response = self.client.post('/mi-ficha/', self.profile_form(telefono='123'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Usa un teléfono chileno local de 9 dígitos o el prefijo +56.')
        self.funcionario.refresh_from_db()
        self.assertIsNone(self.funcionario.telefono)

    def test_personal_profile_changes_password_with_current_password_and_keeps_session(self):
        new_password = 'DiferenteSeguro_2026!'
        response = self.client.post(
            '/mi-ficha/',
            self.profile_form(
                password_actual='TestPassword123!',
                password_nueva=new_password,
                password_confirmacion=new_password,
            ),
        )

        self.assertRedirects(response, '/mi-ficha/')
        self.funcionario.refresh_from_db()
        self.assertTrue(self.funcionario.check_password(new_password))
        self.assertEqual(self.client.get('/mi-ficha/').status_code, 200)

    def test_personal_profile_rejects_wrong_current_password_and_mismatched_new_password(self):
        response = self.client.post(
            '/mi-ficha/',
            self.profile_form(
                password_actual='Incorrecta123!',
                password_nueva='DiferenteSeguro_2026!',
                password_confirmacion='OtraDiferenteSeguro_2026!',
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'La contraseña actual no es correcta.')
        self.assertContains(response, 'Las nuevas contraseñas no coinciden.')
        self.funcionario.refresh_from_db()
        self.assertTrue(self.funcionario.check_password('TestPassword123!'))

    def test_personal_profile_requires_authentication(self):
        self.client.logout()

        response = self.client.get('/mi-ficha/')

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/?next='))

    def test_personal_dashboard_shows_empty_state_when_no_active_employees(self):
        self.funcionario.is_active = False
        self.funcionario.save(update_fields=['is_active'])
        admin = Usuario.objects.create_superuser(
            username='admin.dashboard.empty',
            email='admin@example.com',
            password='TestPassword123!',
            rol=Usuario.Rol.ADMIN,
        )
        self.client.force_login(admin)

        response = self.client.get('/personal/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No hay funcionarios activos')

    def test_anonymous_users_cannot_access_application_pages_or_api(self):
        client = Client()
        protected_urls = (
            '/dashboard/',
            '/semaforo/',
            '/personal/',
            '/verificacion/',
            '/tubo/',
            '/terreno/',
            '/casos-sociales/',
            '/auditoria/',
            '/api/geocodificar/',
            '/api/delegaciones/',
            '/api/usuarios/',
            '/api/metricas/',
            '/api/',
        )

        for url in protected_urls:
            with self.subTest(url=url):
                response = client.get(url)
                if url.startswith('/api/'):
                    self.assertIn(response.status_code, (302, 403))
                else:
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.url.startswith('/login/'))

        self.assertEqual(client.get('/login/').status_code, 200)
        self.assertEqual(client.get('/admin/login/').status_code, 200)
        self.assertEqual(
            client.post('/api/auth/login/', {}, content_type='application/json').status_code,
            400,
        )

    def test_two_factor_verification_requires_password_authenticated_pending_session(self):
        response = Client().post('/verificar-2fa/', {
            'user_id': self.funcionario.pk,
            'code': '123456',
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    @patch('sgr_app.web_views.time.time', return_value=59)
    def test_two_factor_uses_password_pending_session_and_account_totp(self, _mock_time):
        self.funcionario.requires_2fa = True
        self.funcionario.totp_secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
        self.funcionario.save(update_fields=['requires_2fa', 'totp_secret'])
        client = Client()

        password_response = client.post('/login/', {
            'username': self.funcionario.username,
            'password': 'TestPassword123!',
        })
        self.assertEqual(password_response.status_code, 200)
        self.assertTrue(password_response.context['show_2fa'])
        self.assertFalse(password_response.wsgi_request.user.is_authenticated)

        two_factor_response = client.post('/verificar-2fa/', {
            'user_id': '999999',
            'code': '287082',
        })

        self.assertEqual(two_factor_response.status_code, 302)
        dashboard_response = client.get('/personal/')
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(dashboard_response.context['funcionario'].pk, self.funcionario.pk)

    def test_demo_passwords_do_not_authenticate_users(self):
        client = Client()

        response = client.post('/login/', {
            'username': self.funcionario.username,
            'password': 'AdminSGR2026!',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_functionary_cannot_mutate_user_api_or_other_users_commitments(self):
        client = Client()
        client.force_login(self.funcionario)

        response = client.post('/api/usuarios/', {}, content_type='application/json')
        self.assertEqual(response.status_code, 403)

        other = Usuario.objects.create_user(
            username='otro.funcionario',
            password='TestPassword123!',
            rol=Usuario.Rol.FUNCIONARIO,
            delegacion=self.delegacion,
        )
        compromiso = CompromisoAgenda.objects.create(
            solicitante='Vecino de prueba',
            delegacion=self.delegacion,
            responsable=other,
            creado_por=other,
            fecha_compromiso=self.today,
            fecha_comprometida=self.today,
            descripcion='Compromiso de otra persona',
        )
        client.raise_request_exception = False
        response = client.post(f'/tubo/{compromiso.pk}/eliminar/')

        self.assertEqual(response.status_code, 403)
        self.assertTrue(CompromisoAgenda.objects.filter(pk=compromiso.pk).exists())

    def test_authenticated_api_mutations_require_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.funcionario)

        response = client.post('/api/usuarios/', {}, content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def activity_form(self, **overrides):
        data = {
            'funcionario_id': str(self.funcionario.id),
            'fecha_actividad': self.today.isoformat(),
            'item_medicion_id': str(self.item.id),
            'solicitante_id': str(self.solicitante.id),
            'direccion': 'Calle de prueba 123',
            'solicitud_problema': 'Luminaria apagada',
            'accion_ejecutada': 'Se inspeccionó el poste',
            'compromiso_fecha': self.today.isoformat(),
            'compromiso_territorio': 'Sector Centro',
            'compromiso_area_apoyo': 'Operaciones y Territorio',
            'compromiso_descripcion': 'Dar seguimiento a la solicitud',
        }
        data.update(overrides)
        return data

    def test_general_dashboard_displays_calendar_quarter_for_today(self):
        coordinator = Usuario.objects.create_user(
            username='coordinador.dashboard.periodo',
            password='TestPassword123!',
            rol=Usuario.Rol.COORDINADOR,
        )
        self.client.force_login(coordinator)

        response = self.client.get('/dashboard/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['periodo'].id, self.periodo.id)
        self.assertEqual(
            response.context['periodo_nombre_actual'],
            get_nombre_trimestre_actual(self.today),
        )
        self.assertEqual(
            response.context['nombre_periodo_activo'],
            get_nombre_trimestre_actual(self.today),
        )
        self.assertContains(response, get_nombre_trimestre_actual(self.today))

    def test_semaforo_uses_current_quarter_and_admin_thresholds(self):
        self.periodo.umbral_semaforo_verde = 110.0
        self.periodo.umbral_semaforo_ambar = 45.0
        self.periodo.save()

        response = self.client.get('/semaforo/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['periodo_configurado'])
        self.assertEqual(response.context['periodo'].pk, self.periodo.pk)
        self.assertEqual(response.context['umbral_verde'], 110.0)
        self.assertEqual(response.context['umbral_ambar'], 45.0)
        info = response.context['comunal']['info_tiempo']
        self.assertEqual(info['dias_transcurridos'], (self.today - self.period_start).days + 1)
        self.assertEqual(info['dias_totales'], (self.period_end - self.period_start).days + 1)
        self.assertContains(response, 'Días corridos del trimestre.')
        self.assertContains(response, 'del objetivo (Verde)')
        self.assertContains(response, 'del objetivo (Ámbar)')

    def test_unconfigured_quarter_uses_dynamic_dates_and_default_thresholds(self):
        self.periodo.fecha_inicio = date(self.today.year - 1, 7, 1)
        self.periodo.fecha_termino = date(self.today.year - 1, 9, 30)
        self.periodo.save()

        response = self.client.get('/semaforo/')
        periodo_actual, configurado = get_periodo_trimestre_actual(self.today)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(configurado)
        self.assertFalse(response.context['periodo_configurado'])
        self.assertEqual(response.context['periodo'].fecha_inicio, periodo_actual.fecha_inicio)
        self.assertEqual(response.context['periodo'].fecha_termino, periodo_actual.fecha_termino)
        self.assertEqual(response.context['umbral_verde'], 100.0)
        self.assertEqual(response.context['umbral_ambar'], 60.0)
        self.assertContains(response, 'se aplican los umbrales iniciales')
        self.assertNotContains(response, 'Cuarto Trimestre - 2026')

    def test_quarter_label_uses_current_month_and_year(self):
        self.assertEqual(
            get_nombre_trimestre_actual(date(2026, 10, 21)),
            '4° Trimestre (Octubre - Diciembre) - 2026',
        )
        self.assertEqual(
            get_nombre_trimestre_actual(date(2027, 1, 1)),
            '1° Trimestre (Enero - Marzo) - 2027',
        )

    def test_personal_dashboard_displays_calendar_quarter_label(self):
        response = self.client.get('/personal/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'Período: {get_nombre_trimestre_actual(self.today)}')
        self.assertNotContains(response, f'Período: {self.periodo.nombre}')

    def test_personal_dashboard_uses_calendar_quarter_when_previous_period_is_active(self):
        self.periodo.fecha_inicio = date(self.today.year - 1, 7, 1)
        self.periodo.fecha_termino = date(self.today.year - 1, 9, 30)
        self.periodo.save()

        response = self.client.get('/personal/')
        periodo_actual, periodo_configurado = get_periodo_trimestre_actual(self.today)
        dias_transcurridos = (self.today - periodo_actual.fecha_inicio).days + 1
        dias_totales = (periodo_actual.fecha_termino - periodo_actual.fecha_inicio).days + 1

        self.assertEqual(response.status_code, 200)
        self.assertFalse(periodo_configurado)
        self.assertFalse(response.context['periodo_configurado'])
        self.assertEqual(response.context['metricas']['dias_transcurridos'], dias_transcurridos)
        self.assertEqual(response.context['metricas']['dias_totales'], dias_totales)
        self.assertContains(response, f'{dias_transcurridos} / {dias_totales}')
        self.assertContains(response, 'Trimestre actual sin configurar.')
        self.assertNotContains(response, 'Cumplimiento Ponderado Personal')

    def test_activity_registration_saves_requester_and_multiple_evidence(self):
        data = self.activity_form(latitud='-29.9', longitud='-71.2')
        data['fotos'] = [self.upload('foto-1.jpg'), self.upload('foto-2.jpg')]
        with override_settings(MEDIA_ROOT=self.media_dir.name):
            response = self.client.post(
                '/actividad-diaria/registrar-actividad/',
                data,
            )

        self.assertEqual(response.status_code, 302)
        actividad = Actividad.objects.get(funcionario=self.funcionario)
        solicitante = self.solicitante
        self.assertEqual(actividad.solicitante_id, solicitante.id)
        self.assertEqual(actividad.evidencias.count(), 2)
        self.assertEqual(actividad.latitud, -29.9)
        self.assertEqual(actividad.longitud, -71.2)
        compromiso = CompromisoAgenda.objects.get(actividad=actividad)
        self.assertEqual(actividad.compromiso_agenda_id, compromiso.id)
        self.assertEqual(compromiso.fecha_compromiso, self.today)
        self.assertEqual(compromiso.territorio, 'Sector Centro')
        self.assertEqual(compromiso.descripcion, 'Dar seguimiento a la solicitud')

    def test_activity_registration_requires_commitment_details(self):
        data = self.activity_form(compromiso_descripcion='')
        response = self.client.post('/actividad-diaria/registrar-actividad/', data)

        self.assertIn('activity_error=compromiso_datos', response.url)
        self.assertFalse(Actividad.objects.exists())
        self.assertFalse(CompromisoAgenda.objects.exists())

    def test_activity_registration_rejects_invalid_location_coordinates(self):
        response = self.client.post(
            '/actividad-diaria/registrar-actividad/',
            self.activity_form(latitud='91', longitud='-71.2'),
        )

        self.assertIn('activity_error=ubicacion_invalida', response.url)
        self.assertFalse(Actividad.objects.exists())

    def test_invalid_dates_do_not_create_activity(self):
        future = self.today + timedelta(days=1)
        response = self.client.post(
            '/actividad-diaria/registrar-actividad/',
            self.activity_form(
                fecha_actividad=future.isoformat(),
                solicitante_id=str(self.solicitante.id),
            ),
        )
        self.assertIn('activity_error=fecha_futura', response.url)
        self.assertFalse(Actividad.objects.exists())

    def test_activity_registration_rejects_missing_measurement_when_items_exist(self):
        response = self.client.post(
            '/actividad-diaria/registrar-actividad/',
            self.activity_form(item_medicion_id=''),
        )

        self.assertIn('activity_error=item_invalido', response.url)
        self.assertFalse(Actividad.objects.exists())

    def test_invalid_submission_preserves_form_values_after_redirect(self):
        values = self.activity_form(
            fecha_actividad=(self.today + timedelta(days=1)).isoformat(),
            solicitante_id='9999',
            direccion='Pasaje de prueba 456',
        )
        values['solicitante_id'] = str(self.solicitante.id)
        response = self.client.post('/actividad-diaria/registrar-actividad/', values)

        self.assertIn('activity_error=fecha_futura', response.url)
        page = self.client.get(response.url)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'value="{values["fecha_actividad"]}"')
        self.assertContains(page, 'value="Pasaje de prueba 456"')
        self.assertContains(page, f'<option value="{self.solicitante.id}" selected>')
        self.assertContains(page, 'La fecha de la actividad no puede ser posterior a hoy.')
        self.assertNotIn('activity_form_data', self.client.session)

    def test_activity_page_selects_existing_requester(self):
        response = self.client.get('/actividad-diaria/registrar-actividad/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Registrar actividad')
        self.assertContains(response, f'value="{self.solicitante.id}"')
        self.assertContains(response, 'id="mapa-actividad"')
        self.assertContains(response, 'id="btn-ubicacion-actual"')
        self.assertContains(response, 'Cada actividad registrada genera un compromiso de seguimiento.')
        self.assertContains(response, 'name="compromiso_fecha"')
        self.assertNotContains(response, 'name="genera_compromiso"')
        self.assertNotContains(response, 'name="solicitante_run"')

    def test_non_functionary_can_open_activity_form_without_functionary_query(self):
        coordinator = Usuario.objects.create_user(
            username='coordinador.workflow',
            password='TestPassword123!',
            rol=Usuario.Rol.COORDINADOR,
        )
        self.client.force_login(coordinator)

        response = self.client.get('/actividad-diaria/registrar-actividad/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="funcionario_id"')

    def test_requester_registration_creates_validated_requester(self):
        response = self.client.post('/actividad-diaria/registrar-solicitante/', {
            'run': '12.345.678-5',
            'nombre': 'Camila',
            'apellido_paterno': 'Rojas',
            'apellido_materno': 'Pérez',
            'tipo_solicitante': 'VECINO',
            'correo': 'camila@example.com',
            'telefono': '9 8765 4321',
        })

        self.assertEqual(response.status_code, 302)
        solicitante = Solicitante.objects.get(run='12.345.678-5')
        self.assertEqual(solicitante.telefono, '+56987654321')
        self.assertIn(f'solicitante_id={solicitante.id}', response.url)

    def test_requester_registration_shows_validation_errors_without_creating(self):
        response = self.client.post('/actividad-diaria/registrar-solicitante/', {
            'run': '12.345.678-0',
            'nombre': 'Camila',
            'apellido_paterno': 'Rojas',
            'apellido_materno': 'Pérez',
            'tipo_solicitante': 'VECINO',
            'correo': 'correo-invalido',
            'telefono': '99999999999999',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'El dígito verificador del RUN no es válido.')
        self.assertFalse(Solicitante.objects.filter(nombre='Camila').exists())

    def test_requester_registration_rejects_blank_required_fields_and_invalid_choice(self):
        response = self.client.post('/actividad-diaria/registrar-solicitante/', {
            'run': '   ',
            'nombre': '   ',
            'apellido_paterno': '',
            'apellido_materno': '   ',
            'tipo_solicitante': 'NO_VALIDO',
            'correo': '   ',
            'telefono': '',
        })

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        for field in (
            'run',
            'nombre',
            'apellido_paterno',
            'apellido_materno',
            'tipo_solicitante',
            'correo',
        ):
            with self.subTest(field=field):
                self.assertIn(field, form.errors)
        self.assertFalse(Solicitante.objects.filter(nombre='').exists())

    def test_requester_registration_rejects_unformatted_run_bad_email_phone_and_duplicate_run(self):
        cases = (
            ('run', '12345678-5'),
            ('correo', 'correo-invalido'),
            ('telefono', '999999999'),
            ('run', self.solicitante.run),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                data = {
                    'run': '12.345.678-5',
                    'nombre': 'Camila',
                    'apellido_paterno': 'Rojas',
                    'apellido_materno': 'Pérez',
                    'tipo_solicitante': 'VECINO',
                    'correo': 'camila@example.com',
                    'telefono': '9 8765 4321',
                }
                data[field] = value
                response = self.client.post('/actividad-diaria/registrar-solicitante/', data)

                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
                self.assertFalse(Solicitante.objects.filter(nombre='Camila').exists())

    def test_commitment_date_outside_period_is_rejected(self):
        invalid_date = self.period_end + timedelta(days=1)
        response = self.client.post(
            '/actividad-diaria/registrar-actividad/',
            self.activity_form(
                compromiso_fecha=invalid_date.isoformat(),
                compromiso_territorio='Sector Centro',
                compromiso_area_apoyo='Operaciones y Territorio',
                compromiso_descripcion='Seguimiento de la solicitud',
            ),
        )

        self.assertIn('activity_error=fecha_compromiso', response.url)
        self.assertFalse(Actividad.objects.exists())

    def test_commitment_rejects_invalid_selector_values_and_blank_description(self):
        response = self.client.post(
            '/actividad-diaria/registrar-actividad/',
            self.activity_form(
                compromiso_fecha=self.today.isoformat(),
                compromiso_territorio='Territorio inventado',
                compromiso_area_apoyo='Área inventada',
                compromiso_descripcion='   ',
            ),
        )

        self.assertIn('activity_error=compromiso_datos', response.url)
        self.assertFalse(Actividad.objects.exists())

    def test_evidence_only_route_does_not_modify_activity_fields(self):
        actividad = Actividad.objects.create(
            funcionario=self.funcionario,
            delegacion=self.delegacion,
            item_medicion=self.item,
            fecha_actividad=self.today,
            actividad_solicitud='Dato original',
            direccion='Dirección original',
        )
        data = {'fotos': [self.upload('evidencia.jpg')]}
        with override_settings(MEDIA_ROOT=self.media_dir.name):
            response = self.client.post(
                f'/personal/actividades/{actividad.id}/evidencias/',
                data,
            )

        self.assertEqual(response.status_code, 302)
        actividad.refresh_from_db()
        self.assertEqual(actividad.actividad_solicitud, 'Dato original')
        self.assertEqual(actividad.direccion, 'Dirección original')
        self.assertEqual(actividad.evidencias.count(), 1)

    def test_evidence_status_and_compromise_date_stay_synchronized(self):
        actividad = Actividad.objects.create(
            funcionario=self.funcionario,
            delegacion=self.delegacion,
            item_medicion=self.item,
            fecha_actividad=self.today,
        )
        compromiso = CompromisoAgenda.objects.create(
            solicitante='Solicitante de prueba',
            delegacion=self.delegacion,
            responsable=self.funcionario,
            fecha_compromiso=self.today,
            fecha_comprometida=self.today,
            actividad=actividad,
        )
        actividad.compromiso_agenda = compromiso
        actividad.save(update_fields=['compromiso_agenda'])
        evidencia = Evidencia.objects.create(
            actividad=actividad,
            estado=Evidencia.Estado.PENDIENTE,
        )
        compromiso.sincronizar_estado_evidencias()
        self.assertEqual(compromiso.estado_tablero, CompromisoAgenda.Estado.EN_PROCESO)

        evidencia.estado = Evidencia.Estado.APROBADA
        evidencia.save(update_fields=['estado'])
        compromiso.sincronizar_estado_evidencias()
        self.assertEqual(compromiso.estado_tablero, CompromisoAgenda.Estado.COMPLETADO)

        compromiso.fecha_compromiso = self.today - timedelta(days=1)
        compromiso.fecha_comprometida = compromiso.fecha_compromiso
        compromiso.estado = CompromisoAgenda.Estado.EN_PROCESO
        compromiso.save()
        evidencia.estado = Evidencia.Estado.PENDIENTE
        evidencia.save(update_fields=['estado'])
        self.assertEqual(compromiso.estado_tablero, CompromisoAgenda.Estado.VENCIDO)

    def test_editing_commitment_updates_both_date_fields(self):
        coordinator = Usuario.objects.create_user(
            username='coordinador.compromiso.editar',
            password='TestPassword123!',
            rol=Usuario.Rol.COORDINADOR,
        )
        self.client.force_login(coordinator)
        actividad = Actividad.objects.create(
            funcionario=self.funcionario,
            delegacion=self.delegacion,
            fecha_actividad=self.today,
        )
        compromiso = CompromisoAgenda.objects.create(
            solicitante='Solicitante de prueba',
            delegacion=self.delegacion,
            responsable=self.funcionario,
            fecha_compromiso=self.today,
            fecha_comprometida=self.today,
            actividad=actividad,
        )
        nueva_fecha = self.period_end
        response = self.client.post(
            f'/tubo/{compromiso.id}/editar/',
            {
                'solicitante': 'Solicitante actualizado',
                'territorio': 'Sector Centro',
                'fecha_comprometida': nueva_fecha.isoformat(),
                'actividad_id': str(actividad.id),
                'area_apoyo': 'Operaciones y Territorio',
                'descripcion': 'Seguimiento actualizado',
                'observaciones': 'Fecha corregida',
            },
        )

        self.assertEqual(response.status_code, 302)
        compromiso.refresh_from_db()
        self.assertEqual(compromiso.fecha_compromiso, nueva_fecha)
        self.assertEqual(compromiso.fecha_comprometida, nueva_fecha)

    def test_workflow_pages_render(self):
        actividad = Actividad.objects.create(
            funcionario=self.funcionario,
            delegacion=self.delegacion,
            item_medicion=self.item,
            fecha_actividad=self.today,
            direccion='Dirección de prueba',
            latitud=-29.9,
            longitud=-71.2,
        )
        CompromisoAgenda.objects.create(
            solicitante='Solicitante de prueba',
            territorio='Territorio histórico',
            delegacion=self.delegacion,
            responsable=self.funcionario,
            fecha_compromiso=self.today,
            fecha_comprometida=self.today,
            actividad=actividad,
        )

        personal_page = self.client.get('/personal/')
        self.assertContains(personal_page, 'Dirección de prueba')
        self.assertNotContains(personal_page, 'modalRegistroActividad')
        self.assertContains(personal_page, 'Actividad Diaria')
        self.assertContains(self.client.get('/tubo/'), 'Territorio histórico')
        self.assertContains(self.client.get('/terreno/'), 'Dirección de prueba')

    def test_terrain_existing_activity_option_includes_fields_for_prefill(self):
        actividad = Actividad.objects.create(
            funcionario=self.funcionario,
            delegacion=self.delegacion,
            item_medicion=self.item,
            fecha_actividad=self.today,
            direccion='Avenida del Mar 123',
            latitud=-29.9,
            longitud=-71.2,
            accion_ejecutada='Se reparó una luminaria',
        )

        response = self.client.get('/terreno/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-direccion="Avenida del Mar 123"')
        self.assertContains(response, 'data-accion="Se reparó una luminaria"')
        self.assertContains(response, f'data-item-id="{self.item.id}"')
        self.assertContains(response, f'data-item-name="{self.item.nombre_item}"')
        self.assertContains(response, 'id="activity-task-section"')
        self.assertContains(response, 'id="activity-location-section"')
        self.assertContains(response, 'programarBusquedaDireccionCercana')
        self.assertContains(response, 'Buscando la dirección más cercana')

    def test_terrain_evidence_upload_keeps_existing_activity_location(self):
        actividad = Actividad.objects.create(
            funcionario=self.funcionario,
            delegacion=self.delegacion,
            item_medicion=self.item,
            fecha_actividad=self.today,
            direccion='Avenida del Mar 123',
            latitud=-29.9,
            longitud=-71.2,
        )

        with override_settings(MEDIA_ROOT=self.media_dir.name):
            response = self.client.post('/terreno/', {
                'actividad_id': str(actividad.id),
                'fotos': [self.upload('evidencia-terreno.jpg')],
            })

        self.assertEqual(response.status_code, 302)
        actividad.refresh_from_db()
        self.assertEqual(actividad.direccion, 'Avenida del Mar 123')
        self.assertEqual(actividad.latitud, -29.9)
        self.assertEqual(actividad.longitud, -71.2)
        self.assertEqual(actividad.evidencias.count(), 1)

    @patch('urllib.request.urlopen')
    def test_reverse_geocoding_returns_nearest_address_for_map_coordinates(self, mock_urlopen):
        mock_urlopen.return_value = BytesIO(json.dumps({
            'display_name': 'Pasaje Los Huertos 123, La Serena, Chile',
            'address': {
                'road': 'Pasaje Los Huertos',
                'house_number': '123',
                'suburb': 'Las Compañías',
                'city': 'La Serena',
            },
        }).encode('utf-8'))

        response = self.client.get('/api/geocodificar/', {'lat': '-29.9', 'lng': '-71.2'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['direccion_encontrada'], 'Pasaje Los Huertos 123, Las Compañías, La Serena')
        self.assertTrue(response.json()['numero_encontrado'])
        self.assertTrue(response.json()['aproximada'])
        mock_urlopen.assert_called_once()

    def test_reverse_geocoding_rejects_out_of_range_coordinates(self):
        response = self.client.get('/api/geocodificar/', {'lat': '91', 'lng': '-71.2'})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['encontrado'])

    def test_deleting_commitment_removes_its_activity_and_evidence(self):
        coordinator = Usuario.objects.create_user(
            username='coordinador.compromiso.eliminar',
            password='TestPassword123!',
            rol=Usuario.Rol.COORDINADOR,
        )
        self.client.force_login(coordinator)
        actividad = Actividad.objects.create(
            funcionario=self.funcionario,
            delegacion=self.delegacion,
            fecha_actividad=self.today,
        )
        compromiso = CompromisoAgenda.objects.create(
            solicitante='Solicitante de prueba',
            delegacion=self.delegacion,
            responsable=self.funcionario,
            fecha_compromiso=self.today,
            fecha_comprometida=self.today,
            actividad=actividad,
        )
        Evidencia.objects.create(actividad=actividad)

        response = self.client.post(f'/tubo/{compromiso.id}/eliminar/')

        self.assertEqual(response.status_code, 302)
        self.assertFalse(CompromisoAgenda.objects.filter(pk=compromiso.id).exists())
        self.assertFalse(Actividad.objects.filter(pk=actividad.id).exists())
        self.assertFalse(Evidencia.objects.filter(actividad_id=actividad.id).exists())

    def test_rut_validation_checks_format_and_module_11(self):
        self.assertEqual(normalize_chilean_rut('11.111.111-1'), '11.111.111-1')
        self.assertEqual(normalize_chilean_rut('11111111-1'), '11.111.111-1')
        validate_chilean_rut('11.111.111-1')
        for invalid_rut in ('11.111111-1', '11.111.111-2', '111111111'):
            with self.subTest(invalid_rut=invalid_rut):
                with self.assertRaises(ValidationError):
                    normalize_chilean_rut(invalid_rut)
        for unformatted_rut in ('11111111-1', '12345678-5'):
            with self.subTest(unformatted_rut=unformatted_rut):
                with self.assertRaises(ValidationError):
                    validate_chilean_rut(unformatted_rut)

    def test_user_and_requester_store_normalized_rut_and_phone(self):
        user = Usuario.objects.create_user(
            username='usuario.normalizado',
            password='TestPassword123!',
            rut_anonimizado='11.111.111-1',
            telefono='9 1234 5678',
        )
        requester = Solicitante.objects.create(
            run='12.345.678-5',
            nombre='Persona',
            telefono='+56 9 1234 5678',
        )

        self.assertEqual(user.rut_anonimizado, '11.111.111-1')
        self.assertEqual(user.telefono, '+56912345678')
        self.assertEqual(requester.run, '12.345.678-5')
        self.assertEqual(requester.telefono, '+56912345678')

    def test_chilean_phone_validation_normalizes_mobile_and_landline(self):
        self.assertEqual(normalize_chilean_phone('9 1234 5678'), '+56912345678')
        self.assertEqual(normalize_chilean_phone('+56 9 1234 5678'), '+56912345678')
        self.assertEqual(normalize_chilean_phone('+56 2 2345 6789'), '+56223456789')
        self.assertEqual(normalize_chilean_phone('+56 71 234 5678'), '+56712345678')
        for invalid_phone in (
            '+56 9 123 456',
            '56 9 1234 5678',
            '12345678',
            '+56 8 1234 5678',
            '9...1..2..3..4..5..6..7..8',
            '999999999',
            '99999999999999',
        ):
            with self.subTest(invalid_phone=invalid_phone):
                with self.assertRaises(ValidationError):
                    normalize_chilean_phone(invalid_phone)

    def test_user_serializer_validates_and_normalizes_rut_phone_and_email(self):
        invalid = UsuarioSerializer(data={
            'username': 'usuario.invalido',
            'rut_anonimizado': '11.111.111-2',
            'telefono': '555',
            'email': 'correo-invalido',
        })
        self.assertFalse(invalid.is_valid())
        self.assertIn('rut_anonimizado', invalid.errors)
        self.assertIn('telefono', invalid.errors)
        self.assertIn('email', invalid.errors)

        valid = UsuarioSerializer(data={
            'username': 'usuario.valido',
            'rut_anonimizado': '11.111.111-1',
            'telefono': '9 1234 5678',
            'email': 'persona@example.com',
        })
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(valid.validated_data['rut_anonimizado'], '11.111.111-1')
        self.assertEqual(valid.validated_data['telefono'], '+56912345678')

        unformatted = UsuarioSerializer(data={
            'username': 'usuario.run.sin.formato',
            'rut_anonimizado': '11111111-1',
            'email': 'persona@example.com',
        })
        self.assertFalse(unformatted.is_valid())
        self.assertIn('rut_anonimizado', unformatted.errors)

    def test_activity_form_requires_a_registered_requester(self):
        response = self.client.post(
            '/actividad-diaria/registrar-actividad/',
            self.activity_form(solicitante_id=''),
        )
        self.assertIn('activity_error=solicitante', response.url)
        self.assertFalse(Actividad.objects.exists())

    def test_activity_serializer_normalizes_phone_and_rejects_invalid_phone(self):
        actividad = Actividad.objects.create(
            funcionario=self.funcionario,
            delegacion=self.delegacion,
            fecha_actividad=self.today,
        )
        valid = ActividadSerializer(
            actividad,
            data={'contacto_telefono': '9 1234 5678'},
            partial=True,
        )
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(valid.validated_data['contacto_telefono'], '+56912345678')

        invalid = ActividadSerializer(
            actividad,
            data={'contacto_telefono': '12345'},
            partial=True,
        )
        self.assertFalse(invalid.is_valid())
        self.assertIn('contacto_telefono', invalid.errors)

    def test_case_social_serializer_rejects_blank_required_fields(self):
        serializer = CasoSocialSerializer(data={
            'codigo_caso': '   ',
            'persona_anonimizada': ' ',
            'delegacion': self.delegacion.id,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('codigo_caso', serializer.errors)
        self.assertIn('persona_anonimizada', serializer.errors)

    def test_social_attention_serializer_requires_text_and_valid_stage(self):
        serializer = AtencionSocialSerializer(data={
            'caso': 999,
            'etapa': 9,
            'tipo_atencion': ' ',
            'detalle': ' ',
            'resultado': ' ',
            'funcionario': self.funcionario.id,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('etapa', serializer.errors)
        self.assertIn('tipo_atencion', serializer.errors)
        self.assertIn('detalle', serializer.errors)
        self.assertIn('resultado', serializer.errors)

    def test_user_admin_renders_rut_and_phone_format_hints(self):
        admin_user = Usuario.objects.create_superuser(
            username='admin.validation',
            email='admin@example.com',
            password='TestPassword123!',
        )
        self.client.force_login(admin_user)
        response = self.client.get('/admin/sgr_app/usuario/add/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="rut_anonimizado"')
        self.assertContains(response, 'name="telefono"')
        self.assertContains(response, '11.111.111-1, con dígito verificador válido.')

    def test_superadmin_menu_link_is_visible_only_to_superusers(self):
        self.client.force_login(self.funcionario)
        response = self.client.get('/personal/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Django Superadmin')

        superuser = Usuario.objects.create_superuser(
            username='admin.superuser',
            email='superuser@example.com',
            password='TestPassword123!',
        )
        self.client.force_login(superuser)
        response = self.client.get('/personal/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Django Superadmin')
        self.assertContains(response, 'href="/admin/"')
