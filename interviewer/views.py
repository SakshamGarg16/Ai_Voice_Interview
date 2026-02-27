from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream

@csrf_exempt
def initial_twiml(request, session_id):
    response = VoiceResponse()
    response.say("Connecting you to Remi, your AI Recruiter.")
    
    # We use <Connect><Stream> for a bidirectional connection
    connect = Connect()
    
    # Construct the WebSocket URI dynamically based on the current host (ngrok)
    host = request.get_host()
    websocket_url = f"wss://{host}/ws/telephony/{session_id}/"
    
    connect.stream(url=websocket_url)
    response.append(connect)
    
    # Twilio expects an XML response
    return HttpResponse(str(response), content_type='application/xml')