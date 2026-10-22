from datetime import date, timedelta
from django.test import TestCase, Client
from django.utils import timezone
from sgr_app.models import (
    Delegacion, Cargo, Usuario, PeriodoMedicion, ItemMedicion,
    Actividad, Evidencia, CompromisoAgenda, CasoSocial, AtencionSocial,
    RegistroAuditoria, generar_codigo_evidencia
)
from sgr_app.services.calculos import (
    calcular_dias_periodo,
    determinar_color_semaforo,
    calcular_metricas_funcionario,
    calcular_resumen_delegacion,
    calcular_resumen_comunal
)

class MatrizSGRTestSuite(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(nombre="Las Compañías", codigo="CIA")
        self.cargo = Cargo.objects.create(nombre="Gestor Territorial")
        self.usuario = Usuario.objects.create_user(
            username="carlos.test",
            password="Password123!",
            rol=Usuario.Rol.FUNCIONARIO,
            cargo=self.cargo,
            delegacion=self.delegacion,
            first_name="Carlos",
            last_name="Tapia"
        )
        self.verificador = Usuario.objects.create_user(
            username="pablo.cuadra",
            password="Password123!",
            rol=Usuario.Rol.DELEGADO,
            cargo=self.cargo,
            delegacion=self.delegacion,
            first_name="Pablo",
            last_name="Cuadra"
        )
        self.periodo = PeriodoMedicion.objects.create(
            nombre="T3 Test 2026",
            fecha_inicio=date(2026, 7, 1),
            fecha_termino=date(2026, 9, 30),
            tope_cumplimiento=150.0
        )
        # Ítems que suman 100% de ponderación (RN-001)
        self.item1 = ItemMedicion.objects.create(
            cargo=self.cargo, periodo=self.periodo,
            nombre_item="Operativos Terreno", meta_cuantitativa=10.0, ponderador=60.0
        )
        self.item2 = ItemMedicion.objects.create(
            cargo=self.cargo, periodo=self.periodo,
            nombre_item="Atención Solicitudes", meta_cuantitativa=5.0, ponderador=40.0
        )

    # 1. Reglas de Cálculo del Semáforo y Días Computables (RN-007, RN-008)
    def test_dias_computables_y_meta_esperada(self):
        fecha_mitad = date(2026, 8, 15)
        res = calcular_dias_periodo(self.periodo, fecha_mitad)
        self.assertEqual(res['dias_totales'], 92)
        self.assertTrue(0 < res['meta_esperada_pct'] < 100)

    def test_clasificacion_semaforo(self):
        # Verde si avance >= meta esperada
        self.assertEqual(determinar_color_semaforo(50.0, 50.0), 'VERDE')
        self.assertEqual(determinar_color_semaforo(60.0, 50.0), 'VERDE')
        # Ámbar si avance >= 60% de lo esperado y < esperado
        self.assertEqual(determinar_color_semaforo(35.0, 50.0), 'AMBAR')
        self.assertEqual(determinar_color_semaforo(30.0, 50.0), 'AMBAR')
        # Rojo si avance < 60% de lo esperado
        self.assertEqual(determinar_color_semaforo(25.0, 50.0), 'ROJO')

    def test_clasificacion_semaforo_uses_period_thresholds(self):
        self.assertEqual(
            determinar_color_semaforo(55.0, 50.0, umbral_verde=110.0, umbral_ambar=50.0),
            'VERDE',
        )
        self.assertEqual(
            determinar_color_semaforo(52.0, 50.0, umbral_verde=110.0, umbral_ambar=50.0),
            'AMBAR',
        )
        self.assertEqual(
            determinar_color_semaforo(24.0, 50.0, umbral_verde=110.0, umbral_ambar=50.0),
            'ROJO',
        )

    def test_periodic_amber_target_uses_configured_threshold(self):
        self.periodo.umbral_semaforo_ambar = 40.0

        info = calcular_dias_periodo(self.periodo, date(2026, 8, 15))

        self.assertEqual(info['umbral_ambar_ratio'], 40.0)
        self.assertEqual(
            info['umbral_60_dia'],
            round(info['meta_esperada_pct'] * 0.40, 2),
        )

    # 2. Criterio CA-01 y CA-02: Validación de Evidencia Aprobada vs Rechazada
    def test_ca01_ca02_validacion_evidencia(self):
        act = Actividad.objects.create(
            funcionario=self.usuario, delegacion=self.delegacion,
            item_medicion=self.item1, actividad_solicitud="Bacheo pasaje",
            accion_ejecutada="Reparado", fecha_actividad=date(2026, 8, 1)
        )
        ev = Evidencia.objects.create(actividad=act, estado=Evidencia.Estado.PENDIENTE)

        # Pendiente: avance es 0
        m1 = calcular_metricas_funcionario(self.usuario, self.periodo, date(2026, 8, 15))
        item_data = next(i for i in m1['items'] if i['item_id'] == self.item1.id)
        self.assertEqual(item_data['avance_aprobado'], 0)

        # CA-01: Aprobar evidencia aumenta avance a 1
        ev.estado = Evidencia.Estado.APROBADA
        ev.verificador = self.verificador
        ev.save()

        m2 = calcular_metricas_funcionario(self.usuario, self.periodo, date(2026, 8, 15))
        item_data2 = next(i for i in m2['items'] if i['item_id'] == self.item1.id)
        self.assertEqual(item_data2['avance_aprobado'], 1)
        self.assertEqual(item_data2['cumplimiento_pct'], 10.0)

        # CA-02: Rechazar evidencia con observación no suma y conserva motivo
        ev.estado = Evidencia.Estado.RECHAZADA
        ev.observacion = "Foto no nítida"
        ev.save()

        m3 = calcular_metricas_funcionario(self.usuario, self.periodo, date(2026, 8, 15))
        item_data3 = next(i for i in m3['items'] if i['item_id'] == self.item1.id)
        self.assertEqual(item_data3['avance_aprobado'], 0)
        self.assertEqual(ev.observacion, "Foto no nítida")

    # 3. Criterio CA-03: Compromisos Vencidos en Tubo de Trabajo
    def test_ca03_compromiso_vencido(self):
        hoy = timezone.now().date()
        ayer = hoy - timedelta(days=1)
        manana = hoy + timedelta(days=2)

        comp_vencido = CompromisoAgenda.objects.create(
            solicitante="Vecino A", delegacion=self.delegacion,
            responsable=self.usuario, fecha_comprometida=ayer,
            descripcion="Plaza", estado=CompromisoAgenda.Estado.EN_PROCESO
        )
        comp_al_dia = CompromisoAgenda.objects.create(
            solicitante="Vecino B", delegacion=self.delegacion,
            responsable=self.usuario, fecha_comprometida=manana,
            descripcion="Luminaria", estado=CompromisoAgenda.Estado.EN_PROCESO
        )

        resumen = calcular_resumen_delegacion(self.delegacion, self.periodo)
        self.assertEqual(resumen['compromisos']['vencidos'], 1)
        self.assertEqual(resumen['compromisos']['total'], 2)

    # 4. Regla RN-005: Cumplimiento Ponderado con Tope Máximo 150%
    def test_rn005_tope_maximo_cumplimiento(self):
        # Meta es 10 actividades. Registramos 20 actividades aprobadas (200%)
        for i in range(20):
            act = Actividad.objects.create(
                funcionario=self.usuario, delegacion=self.delegacion,
                item_medicion=self.item1, actividad_solicitud=f"Actividad {i}",
                accion_ejecutada="Ejecutada", fecha_actividad=date(2026, 8, 1)
            )
            Evidencia.objects.create(actividad=act, estado=Evidencia.Estado.APROBADA)

        metricas = calcular_metricas_funcionario(self.usuario, self.periodo, date(2026, 8, 15))
        it = next(i for i in metricas['items'] if i['item_id'] == self.item1.id)

        self.assertEqual(it['cumplimiento_pct'], 200.0)
        # Con tope de 150%, aporte ponderado = (60% * 150) / 100 = 90.0%
        self.assertEqual(it['aporte_ponderado'], 90.0)

    # 5. Código Único e Inmutable de Evidencia (RN-010, HU-10)
    def test_generador_codigo_evidencia(self):
        cod = generar_codigo_evidencia("CIA")
        self.assertTrue(cod.startswith("CIA"))
        self.assertEqual(len(cod), 9)

    # 6. Casos Sociales con Secuencia de 3 Etapas (RF-015, CA-04)
    def test_casos_sociales_secuencia_tres_etapas(self):
        caso = CasoSocial.objects.create(
            codigo_caso="CASO-TEST-001", persona_anonimizada="Persona Prueba",
            delegacion=self.delegacion
        )
        AtencionSocial.objects.create(caso=caso, etapa=1, tipo_atencion="Ficha", detalle="E1", resultado="OK", funcionario=self.usuario)
        AtencionSocial.objects.create(caso=caso, etapa=2, tipo_atencion="Visita", detalle="E2", resultado="OK", funcionario=self.usuario)
        AtencionSocial.objects.create(caso=caso, etapa=3, tipo_atencion="Cierre", detalle="E3", resultado="OK", funcionario=self.usuario)
        self.assertEqual(caso.atenciones.count(), 3)

    # 7. Auditoría de Operaciones Críticas (RF-036, CA-09, HU-30)
    def test_ca09_auditoria_operaciones(self):
        RegistroAuditoria.objects.create(
            usuario=self.usuario, accion='CREAR', entidad='Actividad',
            identificador_registro="101", valor_nuevo={'actividad': 'Nueva'}
        )
        self.assertEqual(RegistroAuditoria.objects.filter(identificador_registro="101").count(), 1)

    # 8. Verificación de Vistas Web y RBAC (HTTP 200 y control de acceso)
    def test_vistas_web_integrales(self):
        c = Client()
        # Login
        r_login = c.get('/')
        self.assertEqual(r_login.status_code, 200)

        # Autenticar como delegado
        c.force_login(self.verificador)

        for url in ['/dashboard/', '/personal/', '/verificacion/', '/tubo/', '/terreno/', '/casos-sociales/']:
            resp = c.get(url)
            self.assertEqual(resp.status_code, 200, f"Falla en {url}")

        # Delegado no debe acceder a auditoría (Segregación RNF-008, debe dar 302 redirect)
        resp_auditoria_del = c.get('/auditoria/')
        self.assertEqual(resp_auditoria_del.status_code, 302)

        # Admin sí puede acceder a auditoría (HTTP 200)
        admin_user = Usuario.objects.create_user(
            username='admin.test', password='password123',
            rol=Usuario.Rol.ADMIN
        )
        c.force_login(admin_user)
        resp_auditoria_admin = c.get('/auditoria/')
        self.assertEqual(resp_auditoria_admin.status_code, 200)

    # 10. Seguridad y Segregación de Funciones en API REST (RN-009, CA-07)
    def test_segregacion_funciones_api(self):
        c = Client()
        act = Actividad.objects.create(
            funcionario=self.usuario, delegacion=self.delegacion,
            item_medicion=self.item1, actividad_solicitud="Operativo Terreno",
            accion_ejecutada="Realizado", fecha_actividad=date(2026, 8, 1)
        )
        ev = Evidencia.objects.create(actividad=act, estado=Evidencia.Estado.PENDIENTE)

        # 1. Funcionario intenta auto-aprobarse -> Debe retornar HTTP 403 Forbidden
        c.force_login(self.usuario)
        resp_func = c.post(f"/api/evidencias/{ev.id}/validar/", {'decision': 'APROBADA'}, content_type='application/json')
        self.assertEqual(resp_func.status_code, 403)

        # 2. Delegado de su delegación aprueba -> Debe retornar HTTP 200 OK
        c.force_login(self.verificador)
        resp_del = c.post(f"/api/evidencias/{ev.id}/validar/", {'decision': 'APROBADA'}, content_type='application/json')
        self.assertEqual(resp_del.status_code, 200)
        ev.refresh_from_db()
        self.assertEqual(ev.estado, Evidencia.Estado.APROBADA)

    # 11. Registro de Evidencias de Terreno con Dirección y Múltiples Fotos
    def test_registro_evidencias_terreno_con_direccion_y_fotos(self):
        c = Client()
        c.force_login(self.usuario)
        payload = {
            'funcionario': self.usuario.id,
            'delegacion': self.delegacion.id,
            'item_medicion': self.item1.id,
            'actividad_solicitud': 'Inspección operativa: Balmaceda 1234',
            'accion_ejecutada': 'Bacheo y demarcación de calzada completado.',
            'direccion': 'Balmaceda 1234, La Serena',
            'url_foto_simulada': 'https://ejemplo.cl/foto1.jpg',
            'url_foto_simulada_2': 'https://ejemplo.cl/foto2.jpg',
            'url_foto_simulada_3': 'https://ejemplo.cl/foto3.jpg'
        }
        resp = c.post('/api/actividades/', payload, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['direccion'], 'Balmaceda 1234, La Serena')
        self.assertIsNotNone(data['evidencia'])
        self.assertEqual(data['evidencia']['url_foto_simulada_2'], 'https://ejemplo.cl/foto2.jpg')
        self.assertEqual(data['evidencia']['url_foto_simulada_3'], 'https://ejemplo.cl/foto3.jpg')

    # 12. Métodos del Diagrama de Clases UML (Documento de Soledad Valdebenito)
    def test_metodos_diagrama_clases_soledad(self):
        from sgr_app.models import (
            Actividad, Compromiso, Evidencia, Solicitante, Funcionario,
            Auditoria, Rol, Delegacion, Cargo, Area, Item, Meta, Periodo,
            Indicador, AjusteIncentivo
        )

        # 1. Rol y permisos
        rol_coord = Rol.objects.create(nombre="COORDINADOR", descripcion="Coordinador Comunal")
        self.assertTrue(rol_coord.tienePermiso("GESTIONAR_COORDINACION"))
        self.assertFalse(rol_coord.tienePermiso("PERMISO_INEXISTENTE"))

        # 2. Area
        area_ops = Area.objects.create(nombre="Operaciones y Territorio")
        self.assertTrue(area_ops.activarArea())
        self.assertEqual(area_ops.obtenerCantidadFuncionarios(), 0)

        # 3. Delegacion: activar, desactivar, cumplimiento, semaforo
        self.assertTrue(self.delegacion.activarDelegacion())
        res_sem = self.delegacion.obtenerResumenSemaforo()
        self.assertIn("VERDE", res_sem)

        # 4. Cargo: activar, desactivar
        self.assertTrue(self.cargo.activarCargo())

        # 5. Solicitante y validarRun Módulo 11
        sol = Solicitante.objects.create(run="11.111.111-1", nombre="Juan Pérez")
        # RUN válido de prueba con el formato chileno requerido.
        self.assertTrue(sol.validarRun())
        historial = sol.obtenerHistorial()
        self.assertIsNotNone(historial)

        # 6. Funcionario (Usuario): es_admin, validarRun, registrarActividad, verDashboardPersonal
        func = self.usuario
        func.rut_anonimizado = "11.111.111-1"
        func.save()
        self.assertTrue(func.validarRun())
        self.assertFalse(func.es_admin())
        dash = func.verDashboardPersonal()
        self.assertIn("funcionario", dash)
        self.assertIn("cumplimiento_general", dash)

        # 7. Actividad: asociarSolicitante, generarCompromiso, adjuntarEvidencia
        act = func.registrarActividad(
            fecha_solicitud=date(2026, 8, 1),
            solicitud_problema="Luminaria apagada",
            accion="Reparación luminaria",
            item=self.item1,
            solicitante=sol
        )
        act.asociarSolicitante(sol)
        comp = act.generarCompromiso(
            origen="Vecino Central",
            territorio=self.delegacion,
            fecha_compromiso=date(2026, 8, 20),
            area_apoyo="Alumbrado",
            observacion="Urgente"
        )
        self.assertEqual(comp.solicitante, "Vecino Central")
        evid = act.adjuntarEvidencia("https://ejemplo.cl/evidencia.jpg", descripcion="Foto luminaria")
        self.assertEqual(evid.estado, Evidencia.Estado.PENDIENTE)

        # 8. Compromiso: actualizarEstado, fechaVencida, reprogramarFecha, marcarCompletado
        comp.actualizarEstado("PENDIENTE")
        self.assertTrue(comp.fechaVencida())
        self.assertGreater(comp.calcularDiasAtraso(), 0)
        comp.reprogramarFecha(date(2026, 12, 31), motivo="Falta repuesto")
        self.assertFalse(comp.fechaVencida())
        comp.marcarCompletado()
        self.assertEqual(comp.estado, CompromisoAgenda.Estado.COMPLETADO)

        # 9. Evidencia: cargarArchivo, solicitarValidacion, validarEvidencia, rechazarEvidencia
        evid.solicitarValidacion()
        self.assertEqual(evid.estado, Evidencia.Estado.PENDIENTE)
        evid.validarEvidencia("Aprobado por delegado")
        self.assertEqual(evid.estado, Evidencia.Estado.APROBADA)
        evid.rechazarEvidencia("Rechazado por foto borrosa")
        self.assertEqual(evid.estado, Evidencia.Estado.RECHAZADA)

        # 10. Periodo: evaluarCumplimiento, vigenciaFecha, estaActivo, calcularMetaEsperadaAlDia
        self.assertEqual(self.periodo.evaluarCumplimiento(95.0), "VERDE")
        self.assertEqual(self.periodo.evaluarCumplimiento(65.0), "AMARILLO")
        self.assertEqual(self.periodo.evaluarCumplimiento(30.0), "ROJO")
        self.assertTrue(self.periodo.vigenciaFecha(date(2026, 8, 1)))
        meta_esp = self.periodo.calcularMetaEsperadaAlDia(100.0)
        self.assertGreaterEqual(meta_esp, 0.0)

        # 11. Meta e Indicador
        meta = Meta.objects.create(
            periodo=self.periodo,
            funcionario=func,
            delegacion=self.delegacion,
            valorMeta=10.0,
            ponderador=30.0
        )
        self.assertEqual(meta.obtenerEstadoSemaforo(), "ROJO")
        self.assertTrue(meta.validarPonderacion())
        indicador = Indicador.objects.create(meta=meta, periodo=self.periodo, avance=8.0)
        indicador.actualizarAvance(9.0)
        self.assertEqual(indicador.avance, 9.0)

        # 12. AjusteIncentivo: aplicarAjuste, aprobarAjuste, rechazarAjuste
        admin_u = Usuario.objects.create_user(username="admin.ajustes", password="p", rol=Usuario.Rol.ADMIN)
        ajuste = AjusteIncentivo.objects.create(
            funcionario=func,
            periodo=self.periodo,
            tipo="BONIFICACION",
            valorPorcentaje=10.0,
            estado="PENDIENTE"
        )
        # Funcionario sin permisos lanza PermissionError
        with self.assertRaises(PermissionError):
            ajuste.aprobarAjuste(func)
        # Admin intentando auto-aprobarse su propio ajuste lanza ValueError
        ajuste_propio_admin = AjusteIncentivo.objects.create(
            funcionario=admin_u, periodo=self.periodo, tipo="BONIFICACION", valorPorcentaje=5.0, estado="PENDIENTE"
        )
        with self.assertRaises(ValueError):
            ajuste_propio_admin.aprobarAjuste(admin_u)
        # Admin sí puede aprobar ajuste de otro funcionario
        self.assertTrue(ajuste.aprobarAjuste(admin_u))
        self.assertEqual(ajuste.estado, "APROBADO")
        # Aplicar ajuste suma al porcentaje base
        self.assertEqual(ajuste.aplicarAjuste(80.0), 90.0)

        # 13. Auditoria: registrarAuditoria, consultarHistorial
        log = Auditoria.registrarAuditoria("TEST_EVENT", "Meta", meta.id, {"val": 1}, {"val": 2}, func)
        self.assertIsNotNone(log)
        hist = Auditoria.consultarHistorial("Meta", str(meta.id))
        self.assertEqual(hist.count(), 1)

    # =========================================================================
    # PLAN DE PRUEBAS UNITARIAS - MÓDULO AUTENTICACIÓN (CP-LOGIN-001 a 008)
    # =========================================================================
    def test_cp_login_001_credenciales_validas(self):
        """CP-LOGIN-001: Login con usuario y contraseña válidos -> Autenticación exitosa."""
        c = Client()
        resp = c.post('/login/', {'username': 'carlos.test', 'password': 'Password123!'}, follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/personal/', resp.url)

    def test_cp_login_002_password_incorrecta(self):
        """CP-LOGIN-002: Usuario válido y contraseña incorrecta -> Rechazado."""
        c = Client()
        resp = c.post('/login/', {'username': 'carlos.test', 'password': 'PasswordIncorrecta'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Credenciales inválidas')

    def test_cp_login_003_usuario_inexistente(self):
        """CP-LOGIN-003: Usuario inexistente -> Rechazado."""
        c = Client()
        resp = c.post('/login/', {'username': 'no.existe', 'password': 'Cualquiera123!'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Credenciales inválidas')

    def test_cp_login_004_usuario_vacio(self):
        """CP-LOGIN-004: Usuario vacío -> Validación de campo obligatorio."""
        c = Client()
        resp = c.post('/login/', {'username': '', 'password': 'Password123!'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'El nombre de usuario es obligatorio')

    def test_cp_login_005_password_vacio(self):
        """CP-LOGIN-005: Contraseña vacía -> Validación de campo obligatorio."""
        c = Client()
        resp = c.post('/login/', {'username': 'carlos.test', 'password': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'La contraseña es obligatoria')

    def test_cp_login_006_campos_vacios(self):
        """CP-LOGIN-006: Usuario y contraseña vacíos -> Ambos obligatorios."""
        c = Client()
        resp = c.post('/login/', {'username': '', 'password': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Usuario y contraseña son obligatorios')

    def test_cp_login_007_usuario_inactivo(self):
        """CP-LOGIN-007: Usuario inactivo/bloqueado -> Acceso rechazado."""
        Usuario.objects.create_user(
            username="bloqueado.test",
            password="Password123!",
            is_active=False
        )
        c = Client()
        resp = c.post('/login/', {'username': 'bloqueado.test', 'password': 'Password123!'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Usuario bloqueado o inactivo')

    def test_cp_login_008_formato_invalido_injection(self):
        """CP-LOGIN-008: Datos con formato o caracteres inválidos (SQL Injection/XSS) -> Rechazo seguro."""
        c = Client()
        resp = c.post('/login/', {'username': "' OR '1'='1", 'password': "' OR '1'='1"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Credenciales inválidas')

    # 21. Configuración y Conectividad Cloud AWS (Amazon S3 & Amazon RDS)
    def test_integracion_cloud_aws(self):
        """Verifica la arquitectura Cloud AWS especificada en Documentacion.pdf págs 80-84."""
        from sgr_app.services.aws_service import test_s3_connection, test_rds_connection, is_s3_enabled
        from django.conf import settings

        # 1. Diagnóstico de base de datos relacional (RDS/MySQL o fallback SQLite)
        res_rds = test_rds_connection()
        self.assertIn(res_rds['status'], ['connected', 'local_sqlite'])

        # 2. Diagnóstico de almacenamiento S3 (fallback local seguro si USE_S3=False)
        res_s3 = test_s3_connection()
        self.assertIn(res_s3['status'], ['connected', 'disabled'])

        # 3. Verificación de variables y settings de AWS
        self.assertTrue(hasattr(settings, 'USE_S3'))
        self.assertTrue(hasattr(settings, 'USE_MYSQL'))