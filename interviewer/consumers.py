import json
import asyncio
import websockets
import re
import base64
import struct
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from google import genai
from google.genai import types
from asgiref.sync import sync_to_async
from twilio.rest import Client

import audioop

def create_wav_header(pcm_data, sample_rate=24000, channels=1, bits_per_sample=16):
    byte_count = len(pcm_data)
    header = bytearray()
    header.extend(b'RIFF')
    header.extend(struct.pack('<I', 36 + byte_count))
    header.extend(b'WAVE')
    header.extend(b'fmt ')
    header.extend(struct.pack('<I', 16))
    header.extend(struct.pack('<H', 1))
    header.extend(struct.pack('<H', channels))
    header.extend(struct.pack('<I', sample_rate))
    header.extend(struct.pack('<I', sample_rate * channels * (bits_per_sample // 8)))
    header.extend(struct.pack('<H', channels * (bits_per_sample // 8)))
    header.extend(struct.pack('<H', bits_per_sample))
    header.extend(b'data')
    header.extend(struct.pack('<I', byte_count))
    return header + pcm_data

class TelephonyConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.google_ws = None
        self.stream_sid = None
        self.is_connected = True
        
        # State Tracking
        self.transcript_history = []
        self.user_text_buffer = ""
        self.candidate_name = "Trial Candidate" 
        self.cheating_stats = [] 
        self.baseline_wpm = None
        self.requirements = ""
        self.mandatory_requirements = {}

    async def disconnect(self, close_code):
        self.is_connected = False
        if self.google_ws:
            await self.google_ws.close()
        print("\n[Trial] Call Disconnected.")

    async def receive(self, text_data):
        if not self.is_connected: return
        data = json.loads(text_data)

        if data.get("event") == "start":
            self.stream_sid = data['start']['streamSid']
            self.call_sid = data['start'].get('callSid')
            session_id = self.scope['url_route']['kwargs']['session_id']
            
            print(f"\n[Microservice] Fetching data for session: {session_id}")
            
            # 1. Fetch from Redis
            import redis
            r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
            candidate_raw = r.get(f"session:{session_id}")
            
            if candidate_raw:
                cdata = json.loads(candidate_raw)
                self.candidate_name = cdata.get('candidate_name', 'Candidate')
                self.job_role = cdata.get('job_role', 'Software Engineer')
                self.difficulty = cdata.get('difficulty', 'Medium')
                self.num_questions = cdata.get('num_questions', 2)
                self.ice_breaker = cdata.get('ice_breaker', None)
                self.requirements = cdata.get('requirements', "")
                self.mandatory_requirements = cdata.get('mandatory_requirements', {})
            else:
                # Fallback if Redis expired or not found
                self.candidate_name = "Candidate"
                self.job_role = "Software Engineer"
                self.difficulty = "Medium"
                self.num_questions = 2
                self.ice_breaker = None
                self.requirements = ""
                self.mandatory_requirements = {}

            # 2. Sync to PostgreSQL
            from .models import InterviewSession
            await sync_to_async(InterviewSession.objects.update_or_create)(
                session_id=session_id,
                defaults={
                    'call_sid': self.call_sid, 
                    'candidate_name': self.candidate_name,
                    'job_role': self.job_role,
                    'difficulty': self.difficulty,
                    'num_questions': self.num_questions,
                    'ice_breaker': self.ice_breaker,
                    'requirements': self.requirements,
                    'mandatory_requirements': self.mandatory_requirements
                }
            )
            
            await self.start_gemini_session()

        elif data.get("event") == "media":
            if self.google_ws:
                mu_law_audio = base64.b64decode(data['media']['payload'])
        
                pcm_audio = audioop.ulaw2lin(mu_law_audio, 2)
        
                resampled_pcm, _ = audioop.ratecv(pcm_audio, 2, 1, 8000, 16000, None)
                encoded_pcm = base64.b64encode(resampled_pcm).decode('utf-8')

                await self.google_ws.send(json.dumps({
                        "realtime_input": {
                        "media_chunks": [{
                            "data": encoded_pcm,
                            "mime_type": "audio/pcm;rate=16000" # Change to PCM
                        }]
                    }
                }))

        elif data.get("event") == "stop":
            print("[Trial] Candidate hung up. Processing final report...")
            await self.generate_final_report_terminal()

    async def start_gemini_session(self):
        # Static Prompt for 2-question Trial
        system_prompt = f"""
        You are Ai-Audio Interviewer, an expert Technical Interviewer. You are interviewing {self.candidate_name} for the position of {self.job_role}.
        
        CONTEXT:
        - Job Role: {self.job_role}
        - Difficulty: {self.difficulty}
        - Number of Questions: {self.num_questions}
        - Ice Breaker: {self.ice_breaker if self.ice_breaker else "Briefly introduce yourself and start."}
        - Job Requirements: {self.requirements}
        - Mandatory Requirements (Ask specific questions on these): {json.dumps(self.mandatory_requirements)}
        
        RULES:
        - For Greeting only use candidate's First name not the full name.
        - Question Limit: Exactly {self.num_questions} technical questions tailored to the {self.job_role} role at {self.difficulty} difficulty.
        - IMPORTANT: You MUST evaluate the candidate against the Mandatory Requirements provided. Ask at least one question related to these requirements.
        - Patience: Wait for 3 seconds of silence before responding.
        - Tone: Professional, encouraging, and highly technical.
        
        PROTOCOL:
        - Start: Greet the candidate. Use the Ice Breaker if provided: "{self.ice_breaker if self.ice_breaker else ''}". Otherwise, ask for an introduction.
        - End: After exactly {self.num_questions} questions, say: "Thank you for the interview, {self.candidate_name}. Goodbye."
        - Final Step: ONLY after you have finished speaking the goodbye message, call the `hang_up_call` tool.
        """

        # YOUR EXACT SETUP CONFIG
        setup_msg = {
            "setup": {
                "model": "models/gemini-2.5-flash-native-audio-preview-12-2025",
                "input_audio_transcription": {},
                "output_audio_transcription": {},
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": { "prebuilt_voice_config": { "voice_name": "Kore" } }
                    },
                    "candidate_count": 1,
                },
                "system_instruction": { "parts": [{ "text": system_prompt }] },
                "tools": [{
                    "function_declarations": [{
                        "name": "hang_up_call",
                        "description": "Ends the phone call gracefully after the interview is finished.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {}
                        }
                    }]
                }]
            }
        }

        uri = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={settings.GEMINI_API_KEY}"
        self.google_ws = await websockets.connect(uri)
        await self.google_ws.send(json.dumps(setup_msg))
        
        # Handshake
        await asyncio.sleep(0.5)
        await self.google_ws.send(json.dumps({"client_content": {"turns": [{"role":"user", "parts":[{"text":"Hello!"}]}], "turn_complete": True}}))

        asyncio.create_task(self.listen_to_google())

    async def listen_to_google(self):
        try:
            async for msg in self.google_ws:
                if not self.is_connected: break
                response = json.loads(msg)
                server_content = response.get('serverContent', {})

                # Interruption (Barge-In)
                if 'interruption' in server_content:
                    await self.send(json.dumps({"event": "clear", "streamSid": self.stream_sid}))

                # Relay Audio to Phone
                if 'modelTurn' in server_content:
                    parts = server_content['modelTurn'].get('parts', [])
                    for part in parts:
                        if 'inlineData' in part:
                            pcm_data = base64.b64decode(part['inlineData']['data'])
                            resampled_back, _ = audioop.ratecv(pcm_data, 2, 1, 16000, 8000, None)
                            mu_law_out = audioop.lin2ulaw(resampled_back, 2)
    
                            await self.send(json.dumps({
                                "event": "media",
                                "streamSid": self.stream_sid,
                                "media": { "payload": base64.b64encode(mu_law_out).decode('utf-8') }
                            }))

                # Real-time Transcript Tracking
                if 'speechRecognitionResult' in server_content:
                    text = server_content['speechRecognitionResult'].get('transcript', '')
                    if text:
                        print(f"Candidate: {text}")
                        self.transcript_history.append(f"User: {text}")

                # Tool Call Handling
                if 'toolCall' in response:
                    for call in response['toolCall'].get('functionCalls', []):
                        if call['name'] == 'hang_up_call':
                            print("\n[Tool Call] hang_up_call triggered. Terminating call...")
                            if self.call_sid:
                                try:
                                    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                                    # Terminating the call via REST API
                                    client.calls(self.call_sid).update(status='completed')
                                    print(f"[Twilio] Call {self.call_sid} terminated via API.")
                                except Exception as e:
                                    print(f"[Twilio Error] Could not hang up: {e}")
                            
                            await self.close()
                            return

        except Exception as e:
            print(f"[Google WS Error] {e}")

    async def generate_final_report_terminal(self):
        # Fallback if the tool wasn't called before hangup
        if len(self.transcript_history) > 0:
            print("\n[Trial] Fallback Report:")
            print("\n".join(self.transcript_history))
        await self.close()