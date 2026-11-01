from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView
from .views import *



urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),  
    path('login/', LoginView.as_view(template_name='users/login.html'), name='login'),  
    path('logout/', LogoutView.as_view(next_page='bounty_list'), name='logout'),  
    path('profile/', ProfileDetailView.as_view(), name='profile'),  
    path('collect-bonus/', CollectBonusView.as_view(), name='collect_bonus'),
      
]
