import os
import requests
from django.conf import settings
from google import genai
from google.genai import types
import time
import uuid
import json
import redis
from twilio.rest import Client

def download_recording(recording_url, session_id):
    """Downloads a Twilio recording and saves it locally."""
    save_path = os.path.join(settings.BASE_DIR, 'recordings', f"{session_id}.wav")
    
    # Twilio recordings are protected by Basic Auth
    # Note: Twilio recording URL might need '.wav' appended if it doesn't have it
    if not recording_url.endswith('.wav') and not recording_url.endswith('.mp3'):
        recording_url += '.wav'
        
    response = requests.get(
        recording_url, 
        auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
        stream=True
    )
    
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)
        print(f"[Utils] Recording saved to {save_path}")
        
        # Save path and URL to DB
        from .models import InterviewSession
        try:
            session = InterviewSession.objects.filter(session_id=session_id).first()
            if session:
                session.local_recording_path = save_path
                session.recording_url = recording_url
                session.save()
                print(f"[Utils] Saved recording info to DB for session {session_id}")
        except Exception as e:
            print(f"[Utils Error] Failed to update session in DB: {e}")
            
        return save_path

def analyze_recording_with_gemini(file_path, session_id):
    """Uploads the recording to Gemini and generates a context-aware interview report."""
    from .models import InterviewSession
    
    # Fetch session metadata for a personalized analysis
    session = InterviewSession.objects.filter(session_id=session_id).first()
    candidate_name = session.candidate_name if session else "Candidate"
    job_role = session.job_role if session else "Software Engineer"
    difficulty = session.difficulty if session else "Medium"
    requirements = session.requirements if session else ""
    mandatory_requirements = session.mandatory_requirements if session else {}

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    print(f"[Gemini] Analyzing interview for {candidate_name} ({job_role})...")
    
    # Upload binary file
    with open(file_path, 'rb') as f:
        file_payload = f.read()

    prompt = f"""
    You are an expert Interview Analyst. I have provided a recording of a technical interview.
    
    INTERVIEW CONTEXT:
    - Candidate Name: {candidate_name}
    - Job Role: {job_role}
    - Interview Difficulty: {difficulty}
    - Job Requirements: {requirements}
    - Mandatory Requirements (Evaluate strictly against these): {json.dumps(mandatory_requirements)}
    
    TASK:
    Please listen to the entire conversation and generate a comprehensive interview report. 
    Evaluate the candidate's performance specifically against the requirements of a {job_role} at a {difficulty} level.
    Crucially, verify if they met the Mandatory Requirements provided.
    
    Format the output as follows:
    1. Technical Score (out of 10)
    2. Communication Score (out of 10)
    3. Compatibility (High/Medium/Low)
    4. Feedback: Detailed strengths and weaknesses based on the specific job role.
    5. Transcript Summary: A bulleted list of the main points discussed.
    6. Recommendation: Final hire/no-hire sentiment with justification.
    """

    try:
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[
                types.Part.from_bytes(data=file_payload, mime_type="audio/wav"),
                prompt
            ]
        )
        
        report = response.text
        print("\n" + "="*30)
        print("GEMINI POST-INTERVIEW REPORT")
        print("="*30)
        print(report)
        print("="*30 + "\n")
        
        # Save to database
        from .models import InterviewSession
        import re

        def extract_field(pattern, text):
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            return match.group(1).strip() if match else None

        # Look up by session_id
        try:
            session = InterviewSession.objects.filter(session_id=session_id).first()
            if session:
                session.full_report = report
                
                # Improved parsing for structured data
                tech_score = extract_field(r"Technical Score.*?(\d+)", report)
                comm_score = extract_field(r"Communication Score.*?(\d+)", report)
                comp = extract_field(r"Compatibility.*?:(.*?)(?:\n|$)", report)
                feedback = extract_field(r"Feedback:(.*?)(?:Transcript Summary|Recommendation|$)", report)
                transcript = extract_field(r"Transcript Summary:(.*?)(?:Recommendation|$)", report)
                recommendation = extract_field(r"Recommendation:(.*?)$", report)
                
                if tech_score: session.technical_score = int(tech_score)
                if comm_score: session.communication_score = int(comm_score)
                if comp: session.compatibility = comp[:20].strip()
                if feedback: session.feedback = feedback.strip()
                if transcript: session.transcript_summary = transcript.strip()
                
                # We'll pass the recommendation in the payload
                session.save()
                
                print(f"[Utils] Analysis saved to database for session {session_id}")

                # Trigger the sync with recommendation
                send_report_to_backend(session_id, recommendation=recommendation)
        except Exception as db_err:
            print(f"[Utils] Database update failed: {db_err}")

        return report

    except Exception as e:
        print(f"[Gemini Error] Analysis failed: {e}")
        return None

def send_report_to_backend(session_id, recommendation=None):
    """Sends the interview report and recording info back to the main remintern backend."""
    from .models import InterviewSession
    session = InterviewSession.objects.filter(session_id=session_id).first()
    if not session:
        return

    # Assuming backend has a matching endpoint
    backend_url = os.getenv("BACKEND_WEBHOOK_URL", "http://localhost:8001/remintern/api/interviews/voice-callback/")
    
    payload = {
        "session_id": session.session_id,
        "candidate_name": session.candidate_name,
        "technical_score": session.technical_score,
        "communication_score": session.communication_score,
        "compatibility": session.compatibility,
        "feedback": session.feedback,
        "full_report": session.full_report,
        "transcript_summary": session.transcript_summary,
        "recording_url": session.recording_url,
        "recommendation": recommendation.strip() if recommendation else None
    }

    files = {}
    if session.local_recording_path and os.path.exists(session.local_recording_path):
        try:
            # Open the file in binary mode
            files['recording_file'] = (
                f"{session.session_id}.wav", 
                open(session.local_recording_path, 'rb'), 
                'audio/wav'
            )
        except Exception as file_err:
            print(f"[Report Error] Failed to open recording for upload: {file_err}")

    try:
        print(f"[Report] Sending results and file for {session_id} to backend...")
        # Use data instead of json for multipart/form-data
        response = requests.post(backend_url, data=payload, files=files, timeout=40)
        
        # Close the file if it was opened
        if 'recording_file' in files:
            files['recording_file'][1].close()

        if response.status_code == 200:
            print(f"[Report] Successfully synced with backend for {session_id}")
        else:
            print(f"[Report Error] Backend returned {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[Report Error] Failed to send report: {e}")

def initiate_ai_interview(target_number, candidate_name, job_role, difficulty="Medium", num_questions=2, ice_breaker=None, requirements=None, mandatory_requirements=None):
    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    twilio_number = settings.TWILIO_PHONE_NUMBER
    base_url = settings.BASE_URL
    
    # Generate unique session ID
    session_id = f"int-{uuid.uuid4().hex[:8]}"
    
    # Populate Redis with candidate info
    try:
        r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
        candidate_data = {
            "candidate_name": candidate_name,
            "job_role": job_role,
            "difficulty": difficulty,
            "num_questions": num_questions,
            "ice_breaker": ice_breaker,
            "requirements": requirements,
            "mandatory_requirements": mandatory_requirements
        }
        r.set(f"session:{session_id}", json.dumps(candidate_data), ex=3600) # Expire in 1 hour
    except Exception as e:
        print(f"[Redis Error] Failed to set session data: {e}")
        # Continue anyway, or handle as error
    
    # Create session in DB
    from .models import InterviewSession
    InterviewSession.objects.create(
        session_id=session_id,
        candidate_name=candidate_name,
        job_role=job_role,
        difficulty=difficulty,
        num_questions=num_questions,
        ice_breaker=ice_breaker,
        requirements=requirements,
        mandatory_requirements=mandatory_requirements
    )

    client = Client(account_sid, auth_token)

    print(f"Initiating call to {candidate_name} ({target_number})")
    print(f"Session ID: {session_id}")
    
    try:
        call = client.calls.create(
            url=f"{base_url}/interviewer/twilio/voice/{session_id}/",
            to=target_number,
            from_=twilio_number,
            record=True,
            recording_channels='mono',
            recording_status_callback=f"{base_url}/interviewer/twilio/recording-callback/{session_id}/"
        )
        print(f"Call Succeeded! SID: {call.sid}")
        
        # Update session with call_sid
        session = InterviewSession.objects.get(session_id=session_id)
        session.call_sid = call.sid
        session.save()
        
        return session_id
    except Exception as e:
        print(f"[Twilio Error] Failed to initiate call: {e}")
        return None
