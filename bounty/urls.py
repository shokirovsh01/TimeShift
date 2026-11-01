from django.urls import path
from .views import *


urlpatterns = [
    path('', BountyListView.as_view(), name='bounty_list'),
    path('create/', BountyCreateView.as_view(), name='create_task'),
    path('task/<int:pk>/take/', TakeTaskView.as_view(), name='take_task'),
    path('task/<int:pk>/complete/',CompleteTaskView.as_view(),name='complete_task',),
]
