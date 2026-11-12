from django.db import models
from django.contrib.auth.models import User 
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator

# Create your models here.


class Skill(models.Model):
    name = models.CharField(max_length=100,unique=True)

    def __str__(self):
        return self.name

class Profile(models.Model):
    user = models.OneToOneField(User,on_delete=models.CASCADE,related_name='profile')
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    specialization = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True,null=True)

    balance_minutes = models.PositiveIntegerField(default=60)
    reputation = models.PositiveIntegerField(default=0)
    daily_bonus_minutes = models.PositiveIntegerField(default=0)
    last_bonus_date = models.DateField(null=True,blank=True)
    last_bonus_time = models.DateTimeField(null=True,blank=True)

    is_pro = models.BooleanField(default=False,verbose_name='PRO-status')
    daily_spent_minutes = models.PositiveIntegerField(default=0)
    last_spend_date = models.DateField(null=True,blank=True)
    
    telegram_username = models.CharField(max_length=100,blank=True,unique=True,null=True)
    telegram_id = models.BigIntegerField(null=True,blank=True,unique=True)
    
    
    created_at = models.DateTimeField(auto_now_add=True)
    skill = models.ManyToManyField(Skill,blank=True,related_name='profiles')

    @property
    def formatted_balance(self):
        if self.balance_minutes == 0:
            return "0 мин."
        
        hours = self.balance_minutes // 60
        remaining_minutes = self.balance_minutes % 60
        
        if hours > 0 and remaining_minutes > 0:
            return f"{hours} ч. {remaining_minutes} мин."
        elif hours > 0:
            return f"{hours} ч."
        else:
            return f"{remaining_minutes} мин."

    def __str__(self):
        return (f'{self.user.username} ({self.balance_minutes}m | Reputation: {self.reputation})')
    
# ---------------------------------------------------------------------------
# ОТЗЫВЫ И РЕЙТИНГ
# ---------------------------------------------------------------------------
# Review — единица оценки участника: author оценивает target_user по шкале 1..10
# и (необязательно) пишет комментарий. Средний балл по всем отзывам о пользователе
# хранится в Profile.reputation и пересчитывается сигналом update_user_reputation
# (см. ниже) при каждом создании/сохранении/удалении отзыва.
# ---------------------------------------------------------------------------
class Review(models.Model):
    # кто оставил отзыв (нельзя оценить самого себя — проверяется в AddReviewView)
    author = models.ForeignKey(User,on_delete=models.CASCADE,related_name='written_reviews')
    # кого оценили; related_name='reviews' → user.reviews.all() — все отзывы о юзере
    target_user = models.ForeignKey(User,on_delete=models.CASCADE,related_name='reviews')
    # оценка целым 1..10 (валидаторы дублируют проверку в AddReviewView — защита в глубину)
    rating = models.IntegerField(validators=[MinValueValidator(1),MaxValueValidator(10)])
    text = models.TextField(blank=True,null=True)  # комментарий, не обязателен
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Отзыв от {self.author.username} для {self.target_user.username} ({self.rating}/10)'

class Follow(models.Model):
    follower = models.ForeignKey(User,on_delete=models.CASCADE,related_name='following')
    following = models.ForeignKey(User,on_delete=models.CASCADE,related_name='followers')   
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'following')

    def __str__(self):
        return f"{self.follower.username} подписан на {self.following.username}"

class Notification(models.Model):
    user = models.ForeignKey(User,on_delete=models.CASCADE,related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Уведомление для {self.user.username}: {self.title}'


class DailyQuestProgress(models.Model):
    user = models.ForeignKey(User,on_delete=models.CASCADE,related_name='quest_progress')
    date = models.DateField(auto_now_add=True)

    created_tasks = models.PositiveIntegerField(default=0)
    completed_tasks = models.PositiveIntegerField(default=0)
    faucet_clicks = models.PositiveIntegerField(default=0)

    is_reward_claimed = models.BooleanField(default=False)

    def check_and_reward(self):
        if self.is_reward_claimed:
            return False

        if self.created_tasks >= 1 and self.completed_tasks >= 1 and self.faucet_clicks >= 1:
            self.is_reward_claimed = True
            self.save()

            profile = self.user.profile
            profile.balance_minutes += 60
            profile.save()

            return True
        return False
    

    def __str__(self):
        return f"Квесты {self.user.username} за {self.date}"

from django.db.models import Avg
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


# ---------------------------------------------------------------------------
# СИГНАЛ: пересчёт репутации при изменении отзывов
# ---------------------------------------------------------------------------
# Срабатывает на post_save и post_delete модели Review, т.е. репутация
# (средний рейтинг) обновляется при: создании отзыва, его редактировании
# (AddReviewView обновляет существующий отзыв) и удалении отзыва.
@receiver([post_save, post_delete], sender=Review)
def update_user_reputation(sender, instance, **kwargs):
    """Profile.reputation = средний rating по всем отзывам instance.target_user.

    Округление арифметическое (int(x + 0.5)), а не built-in round():
    round(4.5) → 4 (банковское округление до чётного), а нам нужно 4.5 → 5.
    """
    try:
        target_profile = instance.target_user.profile
    except Profile.DoesNotExist:
        # профиль ещё не создан (или уже удалён каскадом при удалении юзера) —
        # пересчитывать нечего, не роняем запрос
        return

    # средний балл по всем отзывам о данном пользователе (None, если отзывов нет)
    avg_rating = Review.objects.filter(
        target_user=instance.target_user
    ).aggregate(Avg('rating'))['rating__avg']

    # без отзывов репутация = 0; иначе — округлённое среднее (4.5 → 5)
    target_profile.reputation = int(avg_rating + 0.5) if avg_rating else 0
    # save только одного поля, чтобы не затирать параллельные изменения профиля
    target_profile.save(update_fields=['reputation'])