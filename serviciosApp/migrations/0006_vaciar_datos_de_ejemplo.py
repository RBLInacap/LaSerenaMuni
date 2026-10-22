from django.db import migrations


def vaciar_datos_de_ejemplo(apps, schema_editor):
    Requisito = apps.get_model('serviciosApp', 'Requisito')
    Servicio = apps.get_model('serviciosApp', 'Servicio')
    Categoria = apps.get_model('serviciosApp', 'Categoria')
    Solicitud = apps.get_model('solicitudesApp', 'Solicitud')
    alias = schema_editor.connection.alias

    Requisito.objects.using(alias).all().delete()
    Servicio.objects.using(alias).all().delete()
    Categoria.objects.using(alias).all().delete()
    Solicitud.objects.using(alias).all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('serviciosApp', '0005_reponer_datos_iniciales'),
        ('solicitudesApp', '0003_alter_solicitud_id'),
    ]

    operations = [
        migrations.RunPython(vaciar_datos_de_ejemplo, migrations.RunPython.noop),
    ]