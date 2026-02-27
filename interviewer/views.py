from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Start

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

from .utils import download_recording, analyze_recording_with_gemini

@csrf_exempt
def recording_callback(request, session_id):
    # This endpoint is called by Twilio when the recording is ready
    recording_url = request.POST.get('RecordingUrl')
    
    print(f"\n[Recording] Received callback for session: {session_id}")
    
    if recording_url:
        local_file = download_recording(recording_url, session_id)
        
        if local_file:
            analyze_recording_with_gemini(local_file, session_id)
    
    return HttpResponse(status=200)