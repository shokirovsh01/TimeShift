from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.shortcuts import redirect,get_object_or_404,render
from datetime import timedelta
from django.contrib import messages
from datetime import date
from django.db import transaction
from django.views.generic import *
from .models import *
from .forms import ProfileEditForm



class RegisterView(CreateView):
    form_class = UserCreationForm
    template_name = 'users/register.html'
    success_url = reverse_lazy('login')


class ProfileDetailView(LoginRequiredMixin,DeleteView):
    model = User
    template_name = 'users/profile.html'
    context_object_name = 'profile_user'

    def get_object(self):
        return self.request.user

    def get_context_data(self, **kwargs):
        """Отзывы о себе — для блока «Отзывы» в profile.html (новые сверху)."""
        context = super().get_context_data(**kwargs)
        # self.object здесь = request.user (см. get_object);
        # select_related('author__profile') — одна SQL-выборка вместо N+1
        context['reviews'] = (
            self.object.reviews
            .select_related('author__profile')
            .order_by('-created_at')
        )
        return context

class CollectBonusView(LoginRequiredMixin,View):
    def get(self, request):
        profile = request.user.profile
        now = timezone.now()

        if profile.last_bonus_date != now.date():
            profile.daily_bonus_minutes = 0
            profile.last_bonus_date = now.date()

        if profile.daily_bonus_minutes >= 300:
            messages.error(request,'Дневной лимит исчерпан. Приходи завтра!')
            return redirect('profile')
        
        if profile.last_bonus_time is not None:
            if hasattr(profile.last_bonus_time, 'time'): 
                time_passed = now - profile.last_bonus_time
                if time_passed < timedelta(minutes=20):
                    messages.warning(request, "20 минут еще не прошло!")
                    return redirect('profile')

        profile.balance_minutes += 20
        profile.daily_bonus_minutes += 20
        profile.last_bonus_time = now
        profile.save()

        quest,created = DailyQuestProgress.objects.get_or_create(
            user=request.user,
            date=now.date()
        )
        quest.faucet_clicks += 1
        quest.save()

        if quest.check_and_reward():
            messages.success(request,"Ежедневный квест выполнен! +60 минут на баланс 🎁")

        messages.success(request,'Бонус +20 минут успешно получен!')
        return redirect('profile')

# ---------------------------------------------------------------------------
# ОТЗЫВЫ И РЕЙТИНГ
# ---------------------------------------------------------------------------
class AddReviewView(LoginRequiredMixin, View):
    """POST /user/<username>/review/ (name='add_review') — оставить отзыв о пользователе.

    Правила:
      * оценка — обязательное целое 1..10;
      * комментарий — необязательный текст до 2000 символов;
      * нельзя оценить самого себя;
      * один автор — один отзыв: повторная отправка обновляет существующий
        (а не создаёт дубликат — иначе можно накручивать/портить рейтинг);
      * репутация получателя пересчитывается автоматически сигналом
        post_save → update_user_reputation (users/models.py).
    Шаблона-«страницы» у формы нет: она POST-ится из карточки
    «Оставить отзыв» на /user/<username>/ (templates/users/user_profile.html).
    """

    def post(self, request, username):
        target_user = get_object_or_404(User, username=username)

        # отзыва о самом себе быть не может
        if target_user == request.user:
            messages.error(request, "Нельзя оставить отзыв самому себе.")
            return redirect('user_profile', username=username)

        # нормализуем вход: " 5 " → "5"; комментарий без краевых пробелов
        rating = (request.POST.get('rating') or '').strip()
        text = (request.POST.get('text') or '').strip()

        # валидация оценки: непустая строка-число строго в диапазоне 1..10
        # (isdigit() отсекает "5.0", "-3", "abc" и т.п.)
        if not rating.isdigit() or not (1 <= int(rating) <= 10):
            messages.error(request, "Оценка должна быть числом от 1 до 10.")
            return redirect('user_profile', username=username)

        # в модели нет max_length у text — ограничиваем здесь, защита от мусора
        if len(text) > 2000:
            messages.error(request, "Комментарий слишком длинный — максимум 2000 символов.")
            return redirect('user_profile', username=username)

        # upsert вручную (не update_or_create): filter().first() не падает,
        # если в БД уже есть легаси-дубликаты от старой версии без этой проверки
        existing = Review.objects.filter(author=request.user, target_user=target_user).first()
        if existing:
            # обновляем свой прошлый отзыв — post_save пересчитает репутацию
            existing.rating = int(rating)
            existing.text = text
            existing.save()
            messages.success(request, f"Ваш отзыв о {target_user.username} обновлён!")
        else:
            Review.objects.create(
                author=request.user,
                target_user=target_user,
                rating=int(rating),
                text=text,
            )
            messages.success(request, f"Отзыв для {target_user.username} успешно добавлен!")

        # возвращаем автора на страницу того, кого он оценил — сразу виден результат
        return redirect('user_profile', username=username)

        
class ToggleFollowView(LoginRequiredMixin, View):
    def post(self, request, username):
        target_user = get_object_or_404(User, username=username)

        if target_user == request.user:
            messages.error(request, "Нельзя подписаться на самого себя.")
            return redirect('user_profile', username=username)

        follow,created = Follow.objects.get_or_create(follower=request.user,following=target_user)
        if not created:
            follow.delete()
            messages.success(request, f"Вы отписались от {target_user.username}")
        else:
            messages.success(request, f"Вы подписались на {target_user.username}")

        return redirect('bounty_list')
    
class LeaderboardView(ListView):
    model = Profile
    template_name = 'users/leaderboard.html'
    context_object_name = 'top_profiles'

    def get_queryset(self):
        return Profile.objects.select_related('user').order_by('-balance_minutes')

class BuyProView(LoginRequiredMixin,View):
    def post(self, request):
        profile = request.user.profile
        pro_price = 3000

        if profile.is_pro:
            messages.warning(request,"У вас уже есть PRO-статус!")
            return redirect('profile')
        
        if profile.balance_minutes < pro_price:
            messages.error(request, f"Недостаточно времени! PRO стоит {pro_price} минут.")
            return redirect('profile')

        profile.balance_minutes -= pro_price
        profile.is_pro = True
        profile.save()

        messages.success(request, "Поздравляем! Вы успешно приобрели PRO-статус 🚀")
        return redirect('profile')

class AboutUsView(TemplateView):
    template_name = 'users/about_us.html'


class ProfileUpdateView(LoginRequiredMixin, View):
    """Редактирование своего профиля: данные + аватар."""

    def get(self, request):
        user = request.user
        # заполняем форму текущими значениями
        form = ProfileEditForm(user=user, initial={
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'specialization': user.profile.specialization,
            'bio': user.profile.bio or '',
            'telegram_username': user.profile.telegram_username or '',
        })
        return render(request, 'users/profile_edit.html', {'form': form})

    def post(self, request):
        # request.FILES — обязательно для загрузки аватара
        form = ProfileEditForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Профиль обновлён!')
            return redirect('profile')
        return render(request, 'users/profile_edit.html', {'form': form})


class UserProfileView(DetailView):
    """Публичная страница профиля другого пользователя (для подписки и просмотра)."""
    model = User
    template_name = 'users/user_profile.html'
    context_object_name = 'profile_user'
    slug_field = 'username'
    slug_url_kwarg = 'username'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # подписан ли текущий юзер на владельца страницы (для кнопки)
        context['is_following'] = (
            user.is_authenticated
            and user.following.filter(following=self.object).exists()
        )

        # --- Отзывы и рейтинг (для карточки формы и списка отзывов) ---
        # все отзывы о владельце страницы, новые сверху; author грузим сразу
        # (select_related), чтобы в шаблоне не было N+1-запросов на @username
        reviews = (
            self.object.reviews
            .select_related('author__profile')
            .order_by('-created_at')
        )
        context['reviews'] = reviews

        # 1..10 — варианты оценки для радиокнопок формы (rating_choices)
        context['rating_choices'] = range(1, 11)

        # свой отзыв текущего пользователя — для предзаполнения формы:
        # если он уже оценивал этого юзера, форма показывает прошлую оценку
        # и текст, а кнопка становится «Обновить отзыв»
        context['user_review'] = (
            reviews.filter(author=user).first() if user.is_authenticated else None
        )
        return context

class TransferView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        username = request.POST.get('username')
        recipient = get_object_or_404(User, username=username)

        if recipient == request.user:
            messages.error(request,"Нельзя переводить время самому себе.")
            return redirect('user_profile', username=recipient.username)

        try:
            amount = int(request.POST.get('amount',0))
        except:
            messages.error(request, "Укажите корректную сумму для перевода.")
            return redirect('user_profile', username=recipient.username)

        if amount <= 0 or amount > 3600:
            messages.error(request, "Сумма перевода должна быть больше 0 и не превышать 3600 минут.")
            return redirect('user_profile', username=recipient.username)

        sender_profile = request.user.profile
        recipient_profile = recipient.profile
        today = timezone.now().date()

        if sender_profile.last_spend_date != today:
            sender_profile.daily_spent_minutes = 0
            sender_profile.last_spend_date = today

        daily_limit = 720 if sender_profile.is_pro else 120
        if sender_profile.daily_spent_minutes + amount > daily_limit:
            messages.error(request,
                f"Превышен дневной лимит! Ваш лимит: {daily_limit} мин. "
                f"Уже потрачено сегодня: {sender_profile.daily_spent_minutes} мин."
            )
            return redirect('user_profile', username=recipient.username)

        if sender_profile.balance_minutes < amount:
            messages.error(request, "Недостаточно минут на балансе для перевода.")
            return redirect('user_profile', username=recipient.username)

        with transaction.atomic():
            sender_profile.balance_minutes -= amount
            sender_profile.daily_spent_minutes += amount
            sender_profile.save()

            recipient_profile.balance_minutes += amount
            recipient_profile.save()

            Notification.objects.create(
                user=recipient,
                title='Перевод времени',
                message=f"Вам поступил перевод: {amount} мин. от @{request.user.username}"
            )
        messages.success(request, f"Успешно переведено {amount} мин. пользователю @{recipient.username}!")
        return redirect('user_profile', username=recipient.username)

class NotificationListView(LoginRequiredMixin,ListView):
    model = Notification
    template_name = 'users/notifications.html'
    context_object_name = 'notifications'

    def get_queryset(self):
        self.request.user.notifications.filter(is_read=False).update(is_read=True)
        return self.request.user.notifications.order_by('-created_at')
    