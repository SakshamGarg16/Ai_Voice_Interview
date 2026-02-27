from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Change .as_view() to .as_asgi()
    re_path(r'ws/telephony/(?P<session_id>[^/]+)/$', consumers.TelephonyConsumer.as_asgi()),
]