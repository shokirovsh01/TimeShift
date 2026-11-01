from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from .models import *
from users.models import *

@receiver(post_save,sender=HelpContract)
def process_help_contract(sender,instance,created,**kwargs):
    if created:
        task=instance.task
        reward=task.reward_hours

        helper_profile, _ = Profile.objects.get_or_create(user=instance.helper)
        helped_profile, _ = Profile.objects.get_or_create(user=instance.helped_user)

        with transaction.atomic():
            if helped_profile.time_balance >= reward:
                helped_profile.time_balance -= reward
            else:
                helped_profile.time_balance = 0
            helped_profile.save()

            helper_profile.time_balance += reward
            helper_profile.reputation += 10
            helper_profile.save()

            task.status = 'completed'
            task.save()

@receiver(post_save,sender=BountyTask)
def notify_followers_on_new_task(sender,instance,created,**kwargs):
    if created:
        followers = Follow.objects.filter(following=instance.creator)

        for follow in followers:
            # web
            Notification.objects.create(
                user = follow.follower,
                title=f"Новая задача от {instance.creator.username}",
                message=f"Пользователь опубликовал запрос: «{instance.title}». Награда: {instance.reward_minutes} минут."
                )

            # tg

            # telegram_id = follow.follower.profile.telegram_id
            # if telegram_id:
            #     send_to_telegram_bot(telegram_id, message)