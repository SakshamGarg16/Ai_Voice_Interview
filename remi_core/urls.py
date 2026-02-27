from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # This includes all the paths we defined in interviewer/urls.py
    path('interviewer/', include('interviewer.urls')), 
]