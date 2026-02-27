import os
import requests
from django.conf import settings
from google import genai
from google.genai import types
import time

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
    
    TASK:
    Please listen to the entire conversation and generate a comprehensive interview report. 
    Evaluate the candidate's performance specifically against the requirements of a {job_role} at a {difficulty} level.
    
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
                
                # Simple parsing for structured data
                tech_score = extract_field(r"Technical Score.*?(\d+)", report)
                comm_score = extract_field(r"Communication Score.*?(\d+)", report)
                comp = extract_field(r"Compatibility.*?:(.*?)$", report)
                
                if tech_score: session.technical_score = int(tech_score)
                if comm_score: session.communication_score = int(comm_score)
                if comp: session.compatibility = comp[:20] # Limit to max_length
                
                session.save()
                print(f"[Utils] Analysis and results saved to database for session {session_id}")
        except Exception as db_err:
            print(f"[Utils] Database update failed: {db_err}")

        return report

    except Exception as e:
        print(f"[Gemini Error] Analysis failed: {e}")
        return None
