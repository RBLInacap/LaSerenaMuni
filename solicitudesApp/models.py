from django.db import models


class Solicitud(models.Model):
	nombre = models.CharField(max_length=150)
	estado = models.CharField(max_length=50)
	sector = models.CharField(max_length=100)
	descripcion = models.TextField()

	def __str__(self):
		return self.nombre
