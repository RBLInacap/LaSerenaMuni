from django.test import TestCase
from django.urls import reverse
from .models import Categoria, Servicio


class ServicioListadoTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		categoria_comercio, _ = Categoria.objects.get_or_create(nombre='Comercio')
		categoria_conduccion, _ = Categoria.objects.get_or_create(nombre='Tránsito')
		Servicio.objects.create(
			nombre='Patente Comercial',
			descripcion='Solicitud de patente comercial',
			dias_habiles=10,
			costo='$150.000',
			categoria=categoria_comercio,
		)
		Servicio.objects.create(
			nombre='Licencia de Conducir',
			descripcion='Renovación de licencia',
			dias_habiles=7,
			costo='$50.000',
			categoria=categoria_conduccion,
		)

	def test_lista_muestra_controles_y_datos(self):
		response = self.client.get(reverse('servicios'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Agregar')
		self.assertContains(response, 'Modificar')
		self.assertContains(response, 'Eliminar')
		self.assertContains(response, 'Buscar')
		self.assertContains(response, 'Patente Comercial')

	def test_busqueda_filtra_servicios(self):
		response = self.client.get(reverse('servicios'), {'q': 'Comercio'})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Patente Comercial')
		self.assertNotContains(response, 'Licencia de Conducir')
