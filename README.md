# Matriz SGR — Municipalidad de La Serena

Aplicación Django para registrar actividades municipales, evidencias de terreno y compromisos, administrar casos sociales y consultar el avance trimestral mediante un semáforo.

## Aplicación principal

La aplicación Matriz SGR se encuentra en [`backend/`](backend/). La guía completa de instalación, configuración, MySQL/WAMP, pruebas y arranque está en [`backend/README.md`](backend/README.md).

Para iniciar en Windows:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Genera una clave privada para Django, colócala en `SECRET_KEY` dentro de `backend/.env` y luego ejecuta:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

La aplicación estará disponible en <http://127.0.0.1:8000/> y el administrador en <http://127.0.0.1:8000/admin/>.

## Estructura

- `backend/`: aplicación Matriz SGR (Django, API REST, plantillas y archivos estáticos).
- `serviciosApp/`, `solicitudesApp/` y `config/`: aplicación Django heredada separada, con su propio `manage.py` en la raíz. No la confundas con la Matriz SGR.
- `static/`, `templates/`: recursos de la aplicación heredada.

## Seguridad antes de publicar

- No subas `.env`, claves AWS, contraseñas, bases SQLite ni contenido de `media/`.
- Usa `backend/.env.example` como plantilla y genera una clave propia; nunca publiques una clave secreta real.
- `DEBUG=True` es únicamente para desarrollo. Configura hosts permitidos, HTTPS, cookies seguras, HSTS, CORS/CSRF y SMTP antes de desplegar.
- No ejecutes `python manage.py poblar_sgr` en una base con información real: crea registros sintéticos de demostración.

## Pruebas

Desde `backend/`, fuerza SQLite para que las pruebas no escriban en una base MySQL configurada localmente:

```powershell
$env:USE_MYSQL = "False"
python manage.py test sgr_app
```
