from django.db import migrations


def corregir_nombre(apps, schema_editor):
    Servicio = apps.get_model('serviciosApp', 'Servicio')
    Servicio.objects.using(schema_editor.connection.alias).filter(
        nombre='Permisos pa drogarse'
    ).update(nombre='Permisos de construcción')


def revertir_nombre(apps, schema_editor):
    Servicio = apps.get_model('serviciosApp', 'Servicio')
    Servicio.objects.using(schema_editor.connection.alias).filter(
        nombre='Permisos de construcción'
    ).update(nombre='Permisos pa drogarse')


class Migration(migrations.Migration):
    dependencies = [
        ('serviciosApp', '0001_initial'),
        ('solicitudesApp', '0002_datos_iniciales'),
    ]

    operations = [
        migrations.RunPython(corregir_nombre, revertir_nombre),
    ]