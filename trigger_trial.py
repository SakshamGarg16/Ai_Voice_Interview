import os
import uuid
import json
import redis
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

def initiate_ai_interview(target_number, candidate_name, job_role, difficulty="Medium", num_questions=2, ice_breaker=None):
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
    ngrok_url = "https://5468-2a09-bac1-36c0-60-00-242-70.ngrok-free.app" 
    
    # Generate unique session ID
    session_id = f"int-{uuid.uuid4().hex[:8]}"
    
    # Populate Redis with candidate info
    r = redis.Redis(host=os.getenv('REDIS_HOST', 'localhost'), port=int(os.getenv('REDIS_PORT', 6379)), decode_responses=True)
    candidate_data = {
        "candidate_name": candidate_name,
        "job_role": job_role,
        "difficulty": difficulty,
        "num_questions": num_questions,
        "ice_breaker": ice_breaker
    }
    r.set(f"session:{session_id}", json.dumps(candidate_data), ex=3600) # Expire in 1 hour
    
    client = Client(account_sid, auth_token)

    print(f"Initiating call to {candidate_name} ({target_number})")
    print(f"Session ID: {session_id}")
    
    call = client.calls.create(
        url=f"{ngrok_url}/interviewer/twilio/voice/{session_id}/",
        to=target_number,
        from_=twilio_number,
        record=True,
        recording_channels='mono',
        recording_status_callback=f"{ngrok_url}/interviewer/twilio/recording-callback/{session_id}/"
    )
    print(f"Call Succeeded! SID: {call.sid}")

if __name__ == "__main__":
    # Example Trigger
    initiate_ai_interview(
        target_number="+917905104347",
        candidate_name="Saksham Garg",
        job_role="Full Stack Developer",
        difficulty="Med",
        num_questions=1,
    )