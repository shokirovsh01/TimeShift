from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.views.generic import *
from .models import *


# Create your views here.

class BountyListView(ListView):
    model = BountyTask
    template_name = 'bounty/bounty_list.html'
    context_object_name = 'tasks'
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset().select_related('creator','performer').prefetch_related('required_skills')

        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        Skill_id = self.request.GET.get('skill')

        if Skill_id:
            queryset = queryset.filter(required_skills__id=Skill_id)
        
        return queryset

    def get_context_data(self, **kwargs):

        context = super().get_context_data(**kwargs)
        context['skills'] = Skill.objects.all()
        context['current_status'] = self.request.GET.get('status', '')
        context['current_skill'] = self.request.GET.get('skill', '')
        return context



class BountyCreateView(LoginRequiredMixin,CreateView):
    model = BountyTask
    fields = ['title','description','reward_hours','required_skills']
    template_name = 'bounty/create_task.html'
    success_url = reverse_lazy('bounty_list')

    def form_valid(self, form):
        form.instance.creator = self.request.user
        return super().form_valid(form)

class TakeTaskView(LoginRequiredMixin,View):
    def get(self,request,pk):
        task = get_object_or_404(BountyTask,pk=pk)

        if task.status == 'open' and task.creator != request.user:
            task.performer = request.user
            task.status = 'in_progress'
            task.save()

        return redirect('bounty_list')

class CompleteTaskView(LoginRequiredMixin,View):
    def get(self,request,pk):
        
        task = get_object_or_404(BountyTask,pk=pk)

        if task.status != 'in_progress' or task.creator != request.user:
            messages.error(request, "Вы не можете закрыть эту задачу.")
            return redirect('bounty_list')

        creator_profile = request.user.profile
        now_date = timezone.now().date()

        if creator_profile.last_spend_date != now_date:
            creator_profile.daily_spent_minutes = 0
            creator_profile.last_spend_date = now_date

        daily_limit = 720 if creator_profile.is_pro else 120

        if creator_profile.daily_spent_minutes + task.reward_minutes > daily_limit:
            messages.error(request,f"Превышен дневной лимит переводов! Ваш лимит: {daily_limit} мин. Попробуйте завтра или купите PRO.") 
            return redirect('bounty_list')

        if creator_profile.balance_minutes < task.reward_minutes:
            messages.error(request, "Недостаточно минут на балансе для оплаты задачи!")
            return redirect('bounty_list')

        creator_profile.daily_spent_minutes += task.reward_minutes
        creator_profile.save()

        task.status = 'completed'
        task.save()

        HelpContract.objects.create(
            task=task,
            customer=task.creator,
            contractor=task.performer,
            hours_transferred=task.reward_minutes
            )
        
        messages.success(request, "Задача успешно закрыта! Минуты переведены исполнителю.")
        return redirect('bounty_list')



