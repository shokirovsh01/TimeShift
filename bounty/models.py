from django.db import models
from django.contrib.auth.models import User 
from users.models import Skill

# Create your models here.

class BountyTask(models.Model):
    STATUS_CHOICES=[
    ("open", "Open"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
    ]
    creator = models.ForeignKey(User,on_delete=models.CASCADE,related_name='created_tasks')
    performer = models.ForeignKey(User,on_delete=models.CASCADE,null=True,blank=True,related_name='assigned_tasks')
    title = models.CharField(max_length=200)
    description = models.TextField()
    required_skills = models.ManyToManyField(Skill,blank=True,related_name='tasks')
    reward_minutes = models.PositiveIntegerField(default=60)
    status = models.CharField(max_length=20,choices=STATUS_CHOICES,default='open')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.title} ({self.reward_minutes} min) - {self.status}'

class HelpContract(models.Model):
    task = models.OneToOneField(BountyTask,on_delete=models.CASCADE,related_name='contract')
    helper = models.ForeignKey(User,on_delete=models.CASCADE,related_name='completed_helps')
    helped_user = models.ForeignKey(User,on_delete=models.CASCADE,related_name='received_helps')
    feedback = models.TextField(blank=True,null=True)
    complated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (
            f'{self.helper.username} -> {self.helped_user.username}'
            f'(Task #{self.task.id})'
            )
