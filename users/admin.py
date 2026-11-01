from django.contrib import admin
from .models import Profile, Skill


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
  list_display = ("id", "name")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
  list_display = ("user", "balance_minutes", "reputation")   