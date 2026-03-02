from django.db import models

class InterviewSession(models.Model):
    session_id = models.CharField(max_length=255, unique=True)
    candidate_name = models.CharField(max_length=255, default="Trial Candidate")
    job_role = models.CharField(max_length=255, default="Software Engineer")
    difficulty = models.CharField(max_length=50, default="Medium")
    ice_breaker = models.TextField(blank=True, null=True)
    requirements = models.TextField(blank=True, null=True)
    mandatory_requirements = models.JSONField(blank=True, null=True)
    num_questions = models.IntegerField(default=2)
    
    call_sid = models.CharField(max_length=255, blank=True, null=True)
    recording_url = models.URLField(blank=True, null=True)
    local_recording_path = models.CharField(max_length=512, blank=True, null=True)
    
    technical_score = models.IntegerField(blank=True, null=True)
    communication_score = models.IntegerField(blank=True, null=True)
    compatibility = models.CharField(max_length=20, blank=True, null=True)
    feedback = models.TextField(blank=True, null=True)
    transcript_summary = models.TextField(blank=True, null=True)
    full_report = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session {self.session_id} - {self.candidate_name}"
