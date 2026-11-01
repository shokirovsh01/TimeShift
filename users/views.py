from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.shortcuts import redirect
from datetime import timedelta
from django.contrib import messages
from django.views.generic import *
from .models import *



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
        
        if profile.last_bonus_date:
            time_passed = now - profile.last_bonus_time
            if time_passed < timedelta(minutes=20):
                messages.warning(request,'20 минут еще не прошло!')
                return redirect('profile')

        profile.balance_minutes += 20
        profile.daily_bonus_minutes += 20
        profile.last_bonus_time = now
        profile.save()

        messages.success(request,'Бонус +20 минут успешно получен!')
        return redirect('profile')
    