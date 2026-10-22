from django.db import migrations


SERVICIOS = [
    {
        "id": 1,
        "nombre": "Permisos pa drogarse",
        "descripcion": "Trámite de permisos y autorizaciones para obras de construcción",
        "requisitos": ["Planos del proyecto", "Certificado de dominio", "Estudio de impacto"],
        "dias_habiles": 15,
        "costo": "$250.000",
        "categoria": "Construcción",
    },
    {
        "id": 2,
        "nombre": "Patente Comercial",
        "descripcion": "Solicitud de patente comercial para emprendimientos y negocios",
        "requisitos": ["RUT", "Documento de identidad", "Propuesta de negocio"],
        "dias_habiles": 10,
        "costo": "$150.000",
        "categoria": "Comercio",
    },
    {
        "id": 3,
        "nombre": "Licencia de Conducir",
        "descripcion": "Renovación y emisión de licencias de conducir",
        "requisitos": ["Cédula de identidad", "Certificado médico", "Fotos carnet"],
        "dias_habiles": 7,
        "costo": "$50.000",
        "categoria": "Tránsito",
    },
    {
        "id": 4,
        "nombre": "Certificados de Dominio",
        "descripcion": "Emisión de certificados que acreditan dominio de propiedades",
        "requisitos": ["Documentos de propiedad", "Carátula de fojas", "Boleta de impuestos"],
        "dias_habiles": 5,
        "costo": "$30.000",
        "categoria": "Catastro",
    },
    {
        "id": 5,
        "nombre": "Permisos de Funcionamiento",
        "descripcion": "Autorización para funcionamiento de establecimientos comerciales",
        "requisitos": ["Licencia comercial", "Acta sanitaria", "Plano del local"],
        "dias_habiles": 12,
        "costo": "$100.000",
        "categoria": "Comercio",
    },
    {
        "id": 6,
        "nombre": "Solicitud de Bonificación",
        "descripcion": "Solicitud de beneficios municipales y subsidios disponibles",
        "requisitos": ["Formulario de solicitud", "Comprobante de ingresos", "Antecedentes socioeconómicos"],
        "dias_habiles": 20,
        "costo": "Sin costo",
        "categoria": "Beneficios",
    },
]

SOLICITUDES = [
    (101, "Solicitud de luminaria defectuosa", "Pendiente", "Centro", "Falta iluminación en la intersección entre Av. Brasil y Calle Los Álamos."),
    (102, "Revisión de bache en avenida principal", "En proceso", "La Serena", "Se reporta deterioro en superficie de la avenida principal con peligro para peatones."),
    (103, "Permiso para feria vecinal", "Aprobada", "Villa Frei", "Solicitud para realizar feria vecinal con actividades culturales y gastronómicas."),
    (104, "Solicita podas de árboles", "Revisión", "La Florida", "Se requieren podas preventivas y retiro de ramas en zona de paso peatonal."),
    (105, "Fuga de agua en calle Los Maitenes", "Pendiente", "Los Maitenes", "Reporte de fuga de agua en vía pública con riesgo de inundación en zona habitacional."),
    (106, "Solicitud de limpieza de alcantarillado", "En proceso", "San Francisco", "Se solicita revisión y limpieza del sistema de alcantarillado por obstrucción recurrente."),
    (107, "Aprobación de feria del barrio", "Aprobada", "El Milagro", "Solicita autorización para evento vecinal con actividades recreativas y venta de productos locales."),
    (108, "Reparación de vereda en esquina escolar", "Revisión", "Las Palmas", "Existe un daño importante en la vereda cerca del establecimiento educacional."),
    (109, "Solicita retiro de basura en plaza", "Pendiente", "Plaza de Armas", "Acumulación de residuos en plaza central que requiere limpieza urgente."),
    (110, "Consulta por señalética vial", "En proceso", "Pueblo Nuevo", "Se solicita instalación de nuevos señalamientos para mejorar tránsito y seguridad."),
]


def cargar_datos(apps, schema_editor):
    Servicio = apps.get_model("serviciosApp", "Servicio")
    Solicitud = apps.get_model("solicitudesApp", "Solicitud")
    Servicio.objects.using(schema_editor.connection.alias).bulk_create(
        [Servicio(**servicio) for servicio in SERVICIOS]
    )
    Solicitud.objects.using(schema_editor.connection.alias).bulk_create(
        [
            Solicitud(
                id=id_solicitud,
                nombre=nombre,
                estado=estado,
                sector=sector,
                descripcion=descripcion,
            )
            for id_solicitud, nombre, estado, sector, descripcion in SOLICITUDES
        ]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("serviciosApp", "0001_initial"),
        ("solicitudesApp", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(cargar_datos, migrations.RunPython.noop),
    ]