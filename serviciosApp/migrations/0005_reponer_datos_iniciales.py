from django.db import migrations


SERVICIOS = [
    {
        'nombre': 'Permisos de construcción',
        'descripcion': 'Trámite de permisos y autorizaciones para obras de construcción',
        'requisitos': ['Planos del proyecto', 'Certificado de dominio', 'Estudio de impacto'],
        'dias_habiles': 15,
        'costo': '$250.000',
        'categoria': 'Construcción',
    },
    {
        'nombre': 'Patente Comercial',
        'descripcion': 'Solicitud de patente comercial para emprendimientos y negocios',
        'requisitos': ['RUT', 'Documento de identidad', 'Propuesta de negocio'],
        'dias_habiles': 10,
        'costo': '$150.000',
        'categoria': 'Comercio',
    },
    {
        'nombre': 'Licencia de Conducir',
        'descripcion': 'Renovación y emisión de licencias de conducir',
        'requisitos': ['Cédula de identidad', 'Certificado médico', 'Fotos carnet'],
        'dias_habiles': 7,
        'costo': '$50.000',
        'categoria': 'Tránsito',
    },
    {
        'nombre': 'Certificados de Dominio',
        'descripcion': 'Emisión de certificados que acreditan dominio de propiedades',
        'requisitos': ['Documentos de propiedad', 'Carátula de fojas', 'Boleta de impuestos'],
        'dias_habiles': 5,
        'costo': '$30.000',
        'categoria': 'Catastro',
    },
    {
        'nombre': 'Permisos de Funcionamiento',
        'descripcion': 'Autorización para funcionamiento de establecimientos comerciales',
        'requisitos': ['Licencia comercial', 'Acta sanitaria', 'Plano del local'],
        'dias_habiles': 12,
        'costo': '$100.000',
        'categoria': 'Comercio',
    },
    {
        'nombre': 'Solicitud de Bonificación',
        'descripcion': 'Solicitud de beneficios municipales y subsidios disponibles',
        'requisitos': ['Formulario de solicitud', 'Comprobante de ingresos', 'Antecedentes socioeconómicos'],
        'dias_habiles': 20,
        'costo': 'Sin costo',
        'categoria': 'Beneficios',
    },
]

SOLICITUDES = [
    ('Solicitud de luminaria defectuosa', 'Pendiente', 'Centro', 'Falta iluminación en la intersección entre Av. Brasil y Calle Los Álamos.'),
    ('Revisión de bache en avenida principal', 'En proceso', 'La Serena', 'Se reporta deterioro en superficie de la avenida principal con peligro para peatones.'),
    ('Permiso para feria vecinal', 'Aprobada', 'Villa Frei', 'Solicitud para realizar feria vecinal con actividades culturales y gastronómicas.'),
    ('Solicita podas de árboles', 'Revisión', 'La Florida', 'Se requieren podas preventivas y retiro de ramas en zona de paso peatonal.'),
    ('Fuga de agua en calle Los Maitenes', 'Pendiente', 'Los Maitenes', 'Reporte de fuga de agua en vía pública con riesgo de inundación en zona habitacional.'),
    ('Solicitud de limpieza de alcantarillado', 'En proceso', 'San Francisco', 'Se solicita revisión y limpieza del sistema de alcantarillado por obstrucción recurrente.'),
    ('Aprobación de feria del barrio', 'Aprobada', 'El Milagro', 'Solicita autorización para evento vecinal con actividades recreativas y venta de productos locales.'),
    ('Reparación de vereda en esquina escolar', 'Revisión', 'Las Palmas', 'Existe un daño importante en la vereda cerca del establecimiento educacional.'),
    ('Solicita retiro de basura en plaza', 'Pendiente', 'Plaza de Armas', 'Acumulación de residuos en plaza central que requiere limpieza urgente.'),
    ('Consulta por señalética vial', 'En proceso', 'Pueblo Nuevo', 'Se solicita instalación de nuevos señalamientos para mejorar tránsito y seguridad.'),
]


def reponer_datos(apps, schema_editor):
    Servicio = apps.get_model('serviciosApp', 'Servicio')
    Categoria = apps.get_model('serviciosApp', 'Categoria')
    Requisito = apps.get_model('serviciosApp', 'Requisito')
    Solicitud = apps.get_model('solicitudesApp', 'Solicitud')
    alias = schema_editor.connection.alias

    for datos in SERVICIOS:
        categoria, _ = Categoria.objects.using(alias).get_or_create(nombre=datos['categoria'])
        servicio, _ = Servicio.objects.using(alias).get_or_create(
            nombre=datos['nombre'],
            defaults={
                'descripcion': datos['descripcion'],
                'dias_habiles': datos['dias_habiles'],
                'costo': datos['costo'],
                'categoria_id': categoria.pk,
            },
        )
        for descripcion in datos['requisitos']:
            Requisito.objects.using(alias).get_or_create(
                servicio_id=servicio.pk,
                descripcion=descripcion,
            )

    for nombre, estado, sector, descripcion in SOLICITUDES:
        Solicitud.objects.using(alias).get_or_create(
            nombre=nombre,
            defaults={
                'estado': estado,
                'sector': sector,
                'descripcion': descripcion,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('serviciosApp', '0004_categoria_alter_servicio_categoria'),
        ('solicitudesApp', '0003_alter_solicitud_id'),
    ]

    operations = [
        migrations.RunPython(reponer_datos, migrations.RunPython.noop),
    ]