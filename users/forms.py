from django import forms
from django.contrib.auth.models import User
from .models import Profile


class ProfileEditForm(forms.Form):
    """Форма редактирования профиля: поля User + поля Profile."""

    # --- поля пользователя ---
    username = forms.CharField(label='Логин', max_length=150)
    first_name = forms.CharField(label='Имя', max_length=30, required=False)
    last_name = forms.CharField(label='Фамилия', max_length=150, required=False)

    # --- поля профиля ---
    avatar = forms.ImageField(label='Аватар', required=False)
    specialization = forms.CharField(label='Специализация', max_length=100, required=False)
    bio = forms.CharField(label='О себе', required=False,
                          widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Расскажи о себе...'}))
    telegram_username = forms.CharField(label='Telegram', max_length=100, required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user  # юзер, которого редактируем

    def clean_username(self):
        """Логин должен быть уникальным (себя не исключаем из-за совпадения)."""
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError('Этот логин уже занят.')
        return username

    def clean_telegram_username(self):
        """Telegram-ник в модели уникальный — проверяем уникальность."""
        tg = self.cleaned_data.get('telegram_username', '').strip().lstrip('@')
        if tg and Profile.objects.filter(telegram_username=tg).exclude(user=self.user).exists():
            raise forms.ValidationError('Этот Telegram-ник уже занят.')
        return tg

    def clean_avatar(self):
        """Ограничиваем размер аватара 2 МБ (формат уже проверил Pillow)."""
        avatar = self.cleaned_data.get('avatar')
        if avatar and avatar.size > 2 * 1024 * 1024:
            raise forms.ValidationError('Аватар не должен превышать 2 МБ.')
        return avatar

    def save(self):
        """Сохраняем данные в User и Profile, возвращаем юзера."""
        data = self.cleaned_data

        # поля пользователя
        self.user.username = data['username']
        self.user.first_name = data['first_name']
        self.user.last_name = data['last_name']
        self.user.save()

        # поля профиля
        profile = self.user.profile
        profile.specialization = data['specialization']
        profile.bio = data['bio'] or None
        # пустой Telegram сохраняем как None: в модели unique=True + null=True
        profile.telegram_username = data['telegram_username'] or None
        if data.get('avatar'):  # новый файл не пришёл — старый аватар не трогаем
            profile.avatar = data['avatar']
        profile.save()

        return self.user
