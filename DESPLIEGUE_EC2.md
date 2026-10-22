# Despliegue de La Serena en AWS EC2

Esta guía conserva el proceso para sincronizar GitHub con EC2, usar SQLite, aplicar migraciones, crear el superusuario y ejecutar Django.

## 1. Estado del proyecto

- Repositorio: `https://github.com/daninson7985/La_serena.git`
- Rama: `main`
- Base de datos de despliegue: SQLite
- Aplicaciones: `serviciosApp` y `solicitudesApp`
- Administracion: `/admin/`
- Pagina publica: `/`

No se deben publicar `.env`, `db.sqlite3`, `venv` ni respaldos de datos con usuarios.

## 2. Conectarse a EC2

```bash
ssh -i RUTA_DE_LA_LLAVE.pem ec2-user@IP_PUBLICA
cd /var/www/laserena
source venv/bin/activate
```

## 3. Sincronizar con GitHub

Si la rama local de EC2 tiene una historia divergente, primero conserva una copia de referencia y luego sincroniza la rama desplegada:

```bash
git fetch origin main
git branch respaldo-ec2-antes-de-actualizar
git reset --hard origin/main
```

Comprobar la version instalada:

```bash
git log -1 --oneline
```

## 4. Configurar SQLite

El archivo `.env` no se sube a GitHub. Debe existir en EC2 y contener una configuracion similar:

```env
SECRET_KEY=CAMBIAR_POR_UN_SECRETO_REAL
DEBUG=False
ALLOWED_HOSTS=IP_PUBLICA_O_DOMINIO
DB_USE_MYSQL=0
```

Instalar la dependencia de configuracion:

```bash
python -m pip install python-decouple
```

No es necesario instalar `mysqlclient` cuando `DB_USE_MYSQL=0`.

## 5. Aplicar migraciones

```bash
python manage.py check
python manage.py migrate
```

La migracion `0006_vaciar_datos_de_ejemplo` deja vacias las tablas de la aplicacion para que los datos se ingresen desde Django Admin.

Comprobar cantidades:

```bash
python manage.py shell -c "from serviciosApp.models import Categoria, Servicio, Requisito; from solicitudesApp.models import Solicitud; print(Categoria.objects.count(), Servicio.objects.count(), Requisito.objects.count(), Solicitud.objects.count())"
```

Resultado inicial esperado:

```text
0 0 0 0
```

No ejecutar `loaddata datos.json`: el fixture fue retirado del repositorio para evitar publicar datos sensibles.

## 6. Crear el superusuario

```bash
python manage.py createsuperuser
```

Usar el usuario creado para ingresar en:

```text
http://IP_PUBLICA/admin/
```

Desde Admin se pueden crear y modificar:

- Categorias.
- Servicios.
- Requisitos.
- Solicitudes.

## 7. Ejecutar Django temporalmente

Para exponer el servidor en el puerto 8000:

```bash
nohup python manage.py runserver 0.0.0.0:8000 > django.log 2>&1 &
```

Verificar que el puerto este escuchando:

```bash
ss -ltnp | grep 8000
curl -I http://127.0.0.1:8000/solicitudes/
```

El resultado esperado es `HTTP/1.1 200 OK`.

Abrir desde el navegador:

```text
http://IP_PUBLICA:8000/
http://IP_PUBLICA:8000/solicitudes/
http://IP_PUBLICA:8000/admin/
```

En AWS Security Group se debe permitir TCP `8000` si se accede directamente a ese puerto.

## 8. Produccion con Gunicorn y Nginx

La URL sin puerto (`http://IP_PUBLICA/`) normalmente es atendida por Nginx y Gunicorn, no por `runserver`. Luego de actualizar el codigo, reiniciar el servicio:

```bash
sudo systemctl list-units --type=service | grep -Ei "gunicorn|laserena|django"
sudo systemctl restart NOMBRE_DEL_SERVICIO
sudo systemctl status NOMBRE_DEL_SERVICIO --no-pager
```

## 9. Diagnostico rapido

### El puerto 8000 esta ocupado

```bash
ss -ltnp | grep 8000
```

No iniciar un segundo `runserver` si ya existe un proceso escuchando.

### Django devuelve 400 Bad Request

Agregar la IP publica o dominio a `ALLOWED_HOSTS` en `.env` y reiniciar Gunicorn o Django.

### Falta `decouple`

```bash
python -m pip install python-decouple
```

### Falta `MySQLdb`

El proyecto final usa SQLite. Confirmar que `.env` tenga:

```env
DB_USE_MYSQL=0
```

### La base tiene datos inesperados

Verificar que se haya aplicado la migracion final:

```bash
python manage.py showmigrations serviciosApp solicitudesApp
```

La migracion `0006_vaciar_datos_de_ejemplo` debe aparecer con `[X]`.
