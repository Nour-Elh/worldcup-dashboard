from django.urls import path

from .views import dashboard

app_name = 'worldcup'

urlpatterns = [
    path('', dashboard, name='dashboard'),
]
