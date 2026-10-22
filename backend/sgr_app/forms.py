from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password

from sgr_app.models import Solicitante, Usuario
from sgr_app.validators import (
    normalize_chilean_phone,
    normalize_chilean_rut,
    validate_chilean_rut,
)


class SolicitanteForm(forms.ModelForm):
    run = forms.CharField(
        required=True,
        max_length=20,
        error_messages={'required': 'El RUN es obligatorio.'},
    )
    nombre = forms.CharField(
        required=True,
        max_length=100,
        error_messages={'required': 'El nombre es obligatorio.'},
    )
    apellido_paterno = forms.CharField(
        required=True,
        max_length=100,
        error_messages={'required': 'El apellido paterno es obligatorio.'},
    )
    apellido_materno = forms.CharField(
        required=True,
        max_length=100,
        error_messages={'required': 'El apellido materno es obligatorio.'},
    )
    tipo_solicitante = forms.ChoiceField(
        required=True,
        choices=Solicitante.TIPO_SOLICITANTE_CHOICES,
        error_messages={'required': 'Selecciona un tipo de solicitante.'},
    )
    correo = forms.EmailField(
        required=True,
        max_length=254,
        error_messages={
            'required': 'El correo electrónico es obligatorio.',
            'invalid': 'Ingresa un correo electrónico válido.',
        },
    )
    telefono = forms.CharField(required=False, max_length=20)

    class Meta:
        model = Solicitante
        fields = (
            'run',
            'nombre',
            'apellido_paterno',
            'apellido_materno',
            'tipo_solicitante',
            'correo',
            'telefono',
        )

    def clean_run(self):
        value = self.cleaned_data['run']
        try:
            validate_chilean_rut(value)
            return normalize_chilean_rut(value)
        except ValidationError as exc:
            raise ValidationError(exc.messages) from exc

    def clean_telefono(self):
        value = self.cleaned_data.get('telefono', '').strip()
        if not value:
            return ''
        try:
            return normalize_chilean_phone(value)
        except ValidationError as exc:
            raise ValidationError(exc.messages) from exc

    def save(self, commit=True):
        solicitante = super().save(commit=False)
        solicitante.apellido = (
            f"{self.cleaned_data['apellido_paterno']} "
            f"{self.cleaned_data['apellido_materno']}"
        )
        if commit:
            solicitante.save()
            self.save_m2m()
        return solicitante


class MiFichaPersonalForm(forms.ModelForm):
    email_confirmacion = forms.EmailField(
        label='Confirmar correo electrónico',
        required=True,
        max_length=254,
    )
    password_actual = forms.CharField(
        label='Contraseña actual',
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),
    )
    password_nueva = forms.CharField(
        label='Nueva contraseña',
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='Debe cumplir las reglas de seguridad configuradas para el sistema.',
    )
    password_confirmacion = forms.CharField(
        label='Confirmar nueva contraseña',
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    class Meta:
        model = Usuario
        fields = ('first_name', 'last_name', 'email', 'telefono')
        labels = {
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'email': 'Correo electrónico',
            'telefono': 'Teléfono',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'autocomplete': 'given-name', 'maxlength': 150}),
            'last_name': forms.TextInput(attrs={'autocomplete': 'family-name', 'maxlength': 150}),
            'email': forms.EmailInput(attrs={'autocomplete': 'email', 'maxlength': 254}),
            'telefono': forms.TextInput(attrs={'autocomplete': 'tel', 'inputmode': 'tel', 'maxlength': 30}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if Usuario.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Este correo electrónico ya está asociado a otra cuenta.')
        return email

    def clean_telefono(self):
        phone = (self.cleaned_data.get('telefono') or '').strip()
        if not phone:
            return ''
        try:
            return normalize_chilean_phone(phone)
        except ValidationError as exc:
            raise ValidationError(exc.messages) from exc

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        email_confirmacion = cleaned_data.get('email_confirmacion')
        if email and email_confirmacion and email.casefold() != email_confirmacion.strip().casefold():
            self.add_error('email_confirmacion', 'Los correos electrónicos no coinciden.')

        current_password = cleaned_data.get('password_actual')
        new_password = cleaned_data.get('password_nueva')
        password_confirmacion = cleaned_data.get('password_confirmacion')
        if current_password or new_password or password_confirmacion:
            if not current_password:
                self.add_error('password_actual', 'Ingresa tu contraseña actual para cambiarla.')
            elif not self.instance.check_password(current_password):
                self.add_error('password_actual', 'La contraseña actual no es correcta.')
            if not new_password:
                self.add_error('password_nueva', 'Ingresa la nueva contraseña.')
            if new_password and not password_confirmacion:
                self.add_error('password_confirmacion', 'Confirma la nueva contraseña.')
            elif new_password and new_password != password_confirmacion:
                self.add_error('password_confirmacion', 'Las nuevas contraseñas no coinciden.')
            if new_password and new_password == password_confirmacion:
                try:
                    validate_password(new_password, self.instance)
                except ValidationError as exc:
                    self.add_error('password_nueva', exc)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get('password_nueva')
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
            self.save_m2m()
        return user
