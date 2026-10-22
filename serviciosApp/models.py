from django.db import models


class Categoria(models.Model):
	nombre = models.CharField(max_length=100, unique=True)

	def __str__(self):
		return self.nombre


class Servicio(models.Model):
	nombre = models.CharField(max_length=150)
	descripcion = models.TextField()
	dias_habiles = models.PositiveSmallIntegerField()
	costo = models.CharField(max_length=50)
	categoria = models.ForeignKey(
		Categoria,
		on_delete=models.CASCADE,
		related_name='servicios',
	)

	def __str__(self):
		return self.nombre


class Requisito(models.Model):
	servicio = models.ForeignKey(
		Servicio,
		on_delete=models.CASCADE,
		related_name='requisitos',
	)
	descripcion = models.CharField(max_length=200)

	def __str__(self):
		return self.descripcion
