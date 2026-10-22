# Despliegue de Matriz SGR en AWS EC2 con Docker Compose

Esta guía despliega la aplicación Django que vive en `backend/` usando Docker Compose. El `manage.py` de la raíz corresponde a otra aplicación; no se usa para Matriz SGR.

La configuración de ejemplo levanta Django con Gunicorn y MySQL en contenedores, conserva la base de datos en un volumen y sirve los archivos estáticos con WhiteNoise. Las evidencias se guardan en un bucket S3 privado. No expone MySQL ni phpMyAdmin a Internet.

## 1. Preparar AWS

1. Crea una instancia EC2 Ubuntu 24.04 y asígnale un rol IAM con permisos mínimos para listar el bucket S3 de evidencias y leer/escribir sus objetos. Configura los metadatos de la instancia con tokens IMDSv2 requeridos y un límite de salto de respuesta de al menos 2 para que el contenedor pueda obtener el rol IAM.
2. Crea un bucket S3 en la misma región, mantén bloqueado el acceso público y no habilites ACL públicas.
3. En el Security Group permite SSH (puerto 22) solo desde tu IP. Para probar temporalmente la aplicación, permite el puerto 8000 solo desde tu IP; no abras MySQL (3306).
4. Instala Git y Docker Engine con Docker Compose v2:

   ```bash
   sudo apt update
   sudo apt install -y git docker.io docker-compose-v2
   sudo systemctl enable --now docker
   ```

   Los comandos siguientes usan `sudo docker compose` para no requerir acceso permanente al grupo `docker`.

## 2. Configurar la aplicación

En la instancia, clona el repositorio y prepara el archivo de variables:

```bash
git clone <URL_DEL_REPOSITORIO>
cd LaSerenaMuni
cp .env.ec2.example .env.ec2
```

Edita `.env.ec2` en la instancia. Configura, como mínimo:

- `SECRET_KEY`: genera una clave hexadecimal aleatoria con `openssl rand -hex 48`.
- `ALLOWED_HOSTS`: la IP pública o el dominio, sin `http://` ni puerto.
- `DB_PASSWORD` y `DB_ROOT_PASSWORD`: contraseñas distintas y aleatorias.
- `AWS_STORAGE_BUCKET_NAME` y `AWS_S3_REGION_NAME`: bucket creado para evidencias.
- `APP_PORT`: deja `8000`, o cámbialo si ese puerto ya está ocupado.

Con el rol IAM de EC2, deja vacías `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY`. No guardes claves de AWS en el repositorio ni en la imagen Docker. `DEBUG=False` debe permanecer así.

## 3. Construir e iniciar

Desde la raíz del repositorio en EC2:

```bash
sudo docker compose --env-file .env.ec2 up -d db
sudo docker compose --env-file .env.ec2 build web
sudo docker compose --env-file .env.ec2 run --rm web python manage.py migrate --noinput
sudo docker compose --env-file .env.ec2 up -d web
sudo docker compose --env-file .env.ec2 exec web python manage.py createsuperuser
```

Abre `http://IP_PUBLICA:8000/` desde una IP autorizada por el Security Group. Inicia sesión y entra a **Django Superadmin** para configurar delegaciones, funcionarios, períodos de medición e ítems. El despliegue no crea usuarios ni datos de demostración automáticamente.

Ver logs y reiniciar después de actualizar el código:

```bash
sudo docker compose --env-file .env.ec2 logs -f web
git pull
sudo docker compose --env-file .env.ec2 build web
sudo docker compose --env-file .env.ec2 run --rm web python manage.py migrate --noinput
sudo docker compose --env-file .env.ec2 up -d web
```

## 4. HTTPS y datos reales

El ejemplo deja explícitamente desactivado el redireccionamiento HTTPS para permitir una prueba inicial por IP y HTTP. **No uses esa configuración para información personal, casos sociales ni evidencias reales.** Antes de abrir el servicio al público, configura un dominio y HTTPS con un proxy inverso o un Application Load Balancer; luego ajusta `SECURE_SSL_REDIRECT`, las cookies seguras, HSTS y `CSRF_TRUSTED_ORIGINS` en `.env.ec2`. Restringe el puerto 8000 a la red del proxy o ciérralo y publica únicamente HTTPS.

La base de datos del ejemplo vive en un volumen Docker de la instancia. Para producción, planifica respaldos y recuperación, o migra a Amazon RDS. Los archivos de evidencia se guardan en S3 privado mediante el rol IAM de la instancia.

## 5. Diagnóstico

```bash
sudo docker compose --env-file .env.ec2 ps
sudo docker compose --env-file .env.ec2 logs --tail=100 web db
sudo docker compose --env-file .env.ec2 exec web python manage.py check
```

Si la página no carga, verifica que los contenedores estén activos, que `ALLOWED_HOSTS` incluya el host usado en el navegador y que el Security Group permita el puerto configurado desde tu IP. No publiques contraseñas, claves ni el contenido de `.env.ec2` al pedir ayuda.
