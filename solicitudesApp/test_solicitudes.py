from django.test import TestCase
from django.urls import reverse
from .models import Solicitud


class SolicitudListadoTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		Solicitud.objects.create(
			nombre='Solicitud de luminaria defectuosa',
			estado='Pendiente',
			sector='Centro',
			descripcion='Falta iluminación en una calle.',
		)
		Solicitud.objects.create(
			nombre='Revisión de bache en avenida principal',
			estado='En proceso',
			sector='La Serena',
			descripcion='Deterioro en la superficie de la avenida.',
		)

	def test_lista_muestra_controles_y_datos(self):
		response = self.client.get(reverse('solicitudes'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Agregar')
		self.assertContains(response, 'Modificar')
		self.assertContains(response, 'Eliminar')
		self.assertContains(response, 'Buscar')
		self.assertContains(response, 'Solicitud de luminaria defectuosa')

	def test_busqueda_filtra_solicitudes(self):
		response = self.client.get(reverse('solicitudes'), {'q': 'Centro'})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Solicitud de luminaria defectuosa')
		self.assertNotContains(response, 'Revisión de bache en avenida principal')
