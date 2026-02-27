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
            print(f"\n[Trial] Call Started. Stream SID: {self.stream_sid}")
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
        You are Remi, an expert Technical Interviewer. You are interviewing {self.candidate_name} for a Technical role.
        
        RULES:
        - Question Limit: Exactly 2 technical questions.
        - Patience: Wait for 3 seconds of silence before responding.
        - Tone: Professional and encouraging.
        
        PROTOCOL:
        - Start: "Hello. I'm Remi. This is a 2-question trial interview. To start, can you introduce yourself?"
        - End: After questions, say: "Thank you for taking this trial interview. Goodbye."
        - Final Task: Call the `save_report` tool once you have said goodbye.
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
                        "name": "save_report",
                        "description": "Save interview results.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "technical_score": { "type": "INTEGER" },
                                "communication_score": { "type": "INTEGER" },
                                "compatibility": { "type": "STRING", "enum": ["High", "Medium", "Low"] },
                                "feedback": { "type": "STRING" },
                                "transcript_summary": { "type": "STRING" },
                                "full_transcript": { "type": "STRING" }
                            },
                            "required": ["technical_score", "communication_score", "feedback", "compatibility", "transcript_summary", "full_transcript"]
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

                # Tool Call Handling (Terminal Output)
                if 'toolCall' in response:
                    print("\n[Tool Call] save_report triggered by Gemini.")
                    # In trial, we just print the tool arguments to the terminal
                    for call in response['toolCall']['functionCalls']:
                        if call['name'] == 'save_report':
                            print("\n" + "="*30)
                            print("FINAL TRIAL REPORT")
                            print("="*30)
                            print(json.dumps(call['args'], indent=4))
                            print("="*30 + "\n")
                    return

        except Exception as e:
            print(f"[Google WS Error] {e}")

    async def generate_final_report_terminal(self):
        # Fallback if the tool wasn't called before hangup
        if len(self.transcript_history) > 0:
            print("\n[Trial] Fallback Report:")
            print("\n".join(self.transcript_history))
        await self.close()