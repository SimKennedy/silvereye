from django.urls import include, path, reverse_lazy
from django.contrib import admin
from django.views.generic import RedirectView

import silvereye.views as views

urlpatterns = [
    path('', views.UploadResults.as_view(), name='publisher-hub'),
]
