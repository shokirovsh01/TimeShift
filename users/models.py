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
    last_bonus_date = models.DateTimeField(null=True,blank=True)
    last_bonus_time = models.DateField(null=True,blank=True)

    is_pro = models.BooleanField(default=False,verbose_name='PRO-status')
    daily_spent_minutes = models.PositiveIntegerField(default=0)
    last_spend_date = models.DateField(null=True,blank=True)
    
    telegram_username = models.CharField(max_length=100,blank=True,unique=True,null=True)
    telegram_id = models.BigIntegerField(null=True,blank=True,unique=True)
    
    
    created_at = models.DateTimeField(auto_now_add=True)
    skill = models.ManyToManyField(Skill,blank=True,related_name='profiles')

    def __str__(self):
        return (f'{self.user.username} ({self.balance_minutes}m | Reputation: {self.reputation})')
    
class Review(models.Model):
    author = models.ForeignKey(User,on_delete=models.CASCADE,related_name='written_reviews')
    target_user = models.ForeignKey(User,on_delete=models.CASCADE,related_name='reviews') 
    rating = models.IntegerField(validators=[MinValueValidator(1),MaxValueValidator(10)])
    text = models.TextField(blank=True,null=True)
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