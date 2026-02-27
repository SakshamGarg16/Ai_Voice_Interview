import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

def start_trial_call(target_number):
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
    
    ngrok_url = "https://e62284511c2d.ngrok-free.app" 
    
    client = Client(account_sid, auth_token)

    print(f"Calling {target_number}...")
    call = client.calls.create(
        url=f"{ngrok_url}/interviewer/twilio/voice/trial-session-001/",
        to=target_number,
        from_=twilio_number
    )
    print(f"Call successfully triggered! SID: {call.sid}")

if __name__ == "__main__":
    start_trial_call("+917905104347")