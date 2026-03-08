# ReMi AI Voice Interviewer 🎙️🤖

ReMi AI Voice Interviewer is a powerful microservice designed to conduct automated, real-time voice interviews using cutting-edge AI. It combines **Twilio Telephony** with **Google Gemini 2.5 Flash** to provide a seamless, human-like interviewing experience.

## 🚀 Key Features

- **Real-time Voice Interaction**: Bidirectional audio streaming between the candidate's phone and Gemini AI via WebSockets.
- **Context-Aware Interviewing**: Dynamically adjusts questions based on the job role, candidate level, and specific job requirements.
- **Automated Call Control**: The AI is capable of gracefully ending the call using tool-calling when the interview is complete.
- **Deep Post-Interview Analysis**: Automatically downloads the call recording and uses Gemini to generate a structured report including:
  - Technical & Communication Scores
  - Compatibility Rating
  - Detailed Strengths/Weaknesses
  - Full Transcript Summary
  - Hire/No-Hire Recommendation
- **Backend Synchronization**: Syncs interview results and recordings back to your main application via webhooks.

---

## 🛠️ Tech Stack

- **Framework**: [Django](https://www.djangoproject.com/) & [Django Channels](https://channels.readthedocs.io/)
- **ASGI Server**: [Daphne](https://github.com/django/daphne)
- **AI Models**: [Google Gemini 2.5 Flash](https://ai.google.dev/gemini-api/docs/realtime) (Real-time Audio)
- **Telephony**: [Twilio Voice API](https://www.twilio.com/docs/voice)
- **State Management**: [Redis](https://redis.io/)
- **Database**: [PostgreSQL](https://www.postgresql.org/)
- **Audio Processing**: `audioop` (PCM/Mu-law conversion)

---

## ⚙️ Configuration (.env)

Create a `.env` file in the root directory. Use `.env.example` as a template:

```env
# Gemini API Key
GEMINI_API_KEY=your_gemini_api_key

# Twilio Credentials
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=+1234567890

# Public URL (Vital for Twilio Callbacks)
# Use ngrok for local: https://xxxxx.ngrok-free.app
BASE_URL=https://your-public-url.com

# Database (Postgres)
DATABASE_NAME=Voice_AI_db
DATABASE_USER=Voice_AI_user
DATABASE_PASSWORD=...
DATABASE_HOST=localhost
DATABASE_PORT=5433

# Redis
REDIS_HOST=localhost
REDIS_PORT=6380

# Webhook for results
BACKEND_WEBHOOK_URL=https://your-main-app.com/api/callback/
```

---

## 🏃 Running the Project

### Using Docker (Recommended)
```bash
docker-compose up --build
```
This will spin up the Django app (Daphne), PostgreSQL, and Redis.

### Manual Setup
1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Setup Database**:
   ```bash
   python manage.py migrate
   ```
3. **Run Redis**: (Ensure a Redis instance is running on port 6380 or as configured)
4. **Run Server**:
   ```bash
   daphne -b 0.0.0.0 -p 8000 remi_core.asgi:application
   ```

---

## 🧠 Technical Workflow

### 1. Initiation
When an interview is triggered, the service creates an `InterviewSession` and calls the candidate via Twilio. Twilio is instructed to connect to a WebSocket endpoint.

### 2. WebSocket Stream (`TelephonyConsumer`)
Twilio sends a `mu-law` audio stream over a WebSocket.
- **Input**: Mu-law audio is converted to PCM (16kHz) and forwarded to Gemini's Bidi-Generate API.
- **Output**: Gemini returns PCM audio, which is converted back to Mu-law and sent to Twilio to be played to the candidate.

### 3. Tool Calling
Gemini is configured with a `hang_up_call` function. When the AI finishes the interview, it triggers this tool, which makes a REST call to Twilio to terminate the phone call.

### 4. Post-Interview Processing
Once the call ends, Twilio sends a recording callback.
1. The service downloads the `.wav` recording.
2. Gemini analyzes the full audio file for a comprehensive evaluation.
3. The report is parsed and sent to the `BACKEND_WEBHOOK_URL`.

---

## 🔌 API Reference

### Trigger an Interview
**Endpoint**: `POST /interviewer/api/trigger/`

**Payload**:
```json
{
  "target_number": "+91XXXXXXXXXX",
  "candidate_name": "John Doe",
  "job_role": "Python Developer",
  "difficulty": "Hard",
  "num_questions": 3,
  "ice_breaker": "Hey John, glad to have you here!",
  "mandatory_requirements": {
    "Docker": "Must know containerization",
    "Redis": "Needs caching experience"
  }
}
```

---

## 📂 Project Structure

- `interviewer/consumers.py`: Handles the real-time WebSocket logic and Gemini integration.
- `interviewer/utils.py`: Contains telephony helper functions, Gemini analysis, and recording downloads.
- `interviewer/views.py`: API endpoints for Twilio TwiML and internal triggers.
- `remi_core/`: Main Django project configuration.
- `recordings/`: Local storage for downloaded interview audio.

---

*Built with ❤️ for the next generation of automated hiring.*
