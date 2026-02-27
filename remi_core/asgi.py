import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import interviewer.routing # Import your routing file

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'remi_core.settings')

application = ProtocolTypeRouter({
    # Standard HTTP requests
    "http": get_asgi_application(),
    
    # WebSocket requests (Twilio Media Streams)
    "websocket": AuthMiddlewareStack(
        URLRouter(
            interviewer.routing.websocket_urlpatterns
        )
    ),
})