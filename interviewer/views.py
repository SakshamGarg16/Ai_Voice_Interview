from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Start
import json
from .utils import initiate_ai_interview

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

@csrf_exempt
def trigger_interview_api(request):
    """API endpoint to trigger an interview from another service."""
    if request.method != 'POST':
        return JsonResponse({"error": "Only POST requests are allowed"}, status=405)
    
    try:
        data = json.loads(request.body)
        target_number = data.get('target_number')
        candidate_name = data.get('candidate_name')
        job_role = data.get('job_role', 'Software Engineer')
        difficulty = data.get('difficulty', 'Medium')
        num_questions = data.get('num_questions', 3)
        ice_breaker = data.get('ice_breaker')
        requirements = data.get('requirements')
        mandatory_requirements = data.get('mandatory_requirements')
        
        if not target_number or not candidate_name:
            return JsonResponse({"error": "target_number and candidate_name are required"}, status=400)
        
        session_id = initiate_ai_interview(
            target_number=target_number,
            candidate_name=candidate_name,
            job_role=job_role,
            difficulty=difficulty,
            num_questions=num_questions,
            ice_breaker=ice_breaker,
            requirements=requirements,
            mandatory_requirements=mandatory_requirements
        )
        
        if session_id:
            return JsonResponse({
                "status": "success",
                "session_id": session_id,
                "message": f"Interview initiated for {candidate_name}"
            })
        else:
            return JsonResponse({"status": "failed", "error": "Could not initiate call"}, status=500)
            
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)