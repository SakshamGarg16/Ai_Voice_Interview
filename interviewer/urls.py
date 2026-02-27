# interviewer/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Change <uuid:session_id> to <str:session_id>
    path('twilio/voice/<str:session_id>/', views.initial_twiml, name='initial_twiml'),
]