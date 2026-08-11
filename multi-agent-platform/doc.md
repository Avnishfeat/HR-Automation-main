# API Documentation - Multi-Agent Platform

This document lists the public API endpoints exposed by the Multi-Agent Platform FastAPI application.

For a complete Interview Agent reference, see [Interview Agent API Reference](docs/interview-agent-api.md).

For internal operational findings and remediation priorities, see the [Interview Agent Stability Audit](docs/interview-agent-stability-audit.md).

For production boot ordering, health monitoring, maintenance-window recovery,
and retention settings, see [Interview Agent Operations](docs/interview-operations.md).

Interview operations are single-session by default and expose health at
`/api/v1/interview/health` and `/api/v1/interview/health/detailed`.
PostgreSQL persists interview lifecycle state and final reports. Actionabl
retrieves a report by its unique `buss_id` through the Interview Agent API;
the platform does not send completion webhooks.

When an external scheduler starts an interview, it can send a stable
`X-Idempotency-Key` header. Retrying the same request with that key returns the
original session instead of starting a duplicate interview.

## Base URLs

Production via nginx:

```text
http://122.170.2.205:7010
```

Interactive API documentation:

```text
http://122.170.2.205:7010/docs
```

OpenAPI schema:

```text
GET /openapi.json
```

## Root

### API Info

```http
GET /
```

Response:

```json
{
  "message": "Multi-Agent Platform API",
  "version": "1.0.0",
  "docs": "/docs"
}
```

## Job Description Agent

Generates structured job descriptions from role, requirements, and optional hiring metadata.

### Generate Job Description

```http
POST /api/v1/jd/generate
Content-Type: application/json
```

Request body:

```json
{
  "job_role": "Data Analyst",
  "requirements": "SQL, Python, Power BI, dashboarding, stakeholder reporting",
  "preferred_skills": "Statistics, data modeling",
  "experience_range": "3-5 years",
  "salary_range": "8-12 LPA",
  "work_location": "Mumbai",
  "job_type": "Full-time",
  "department": "Analytics",
  "jd_shift": "Day shift",
  "joining_timeline": "30 days",
  "travel_requirement": "Occasional",
  "no_of_positions": "2",
  "total_budget": "24 LPA",
  "employee_id": "EMP1001",
  "employee_name": "Recruiter Name",
  "employee_email_id": "recruiter@example.com",
  "reports_to_id": "MGR1001",
  "reports_to_name": "Hiring Manager",
  "reports_to_email": "manager@example.com",
  "job_code": "DA-001",
  "oprations": "INSERT",
  "postion_open_date": "2026-05-18",
  "positionclosedate": "2026-06-18",
  "jd_validity_period": "30 days"
}
```

Required field:

- `requirements`

Response:

```json
{
  "status": true,
  "job_role": "Data Analyst",
  "job_description": {
    "required_skills": "SQL, Python, Power BI",
    "preferred_skills": "Statistics, data modeling",
    "minimum_qualification": "Bachelor's degree",
    "languages": "English",
    "overview": "Role overview...",
    "key_responsibilities": "Responsibilities...",
    "key_skills_and_qualifications": "Skills and qualifications...",
    "desired_attributes": "Attributes...",
    "benefits": "Benefits..."
  }
}
```

### Generate Flat Job Description

```http
POST /api/v1/jd/generate-flat
Content-Type: application/json
```

Uses the same request body as `/api/v1/jd/generate`, but returns generated JD fields at the response root.

Response:

```json
{
  "status": true,
  "required_skills": "SQL, Python, Power BI",
  "preferred_skills": "Statistics, data modeling",
  "minimum_qualification": "Bachelor's degree",
  "languages": "English",
  "overview": "Role overview...",
  "key_responsibilities": "Responsibilities...",
  "key_skills_and_qualifications": "Skills and qualifications...",
  "desired_attributes": "Attributes...",
  "benefits": "Benefits..."
}
```

### JD Health

```http
GET /api/v1/jd/health
```

Response:

```json
{
  "status": "ok",
  "agent": "JD Agent"
}
```

## Talent Matcher Agent

Matches employee profiles against a structured job description.

### Match Employees to Job

```http
POST /api/v1/talent_matcher/match-job
Content-Type: application/json
```

Request body:

```json
{
  "job_role": "Data Analyst",
  "job_description": {
    "required_skills": "SQL, Python, Power BI",
    "preferred_skills": "Statistics",
    "minimum_qualification": "Bachelor's degree",
    "languages": "English",
    "overview": "Analyze business data and build dashboards.",
    "key_responsibilities": "Create reports, dashboards, and insights.",
    "key_skills_and_qualifications": "SQL, Python, BI tools",
    "desired_attributes": "Analytical thinking",
    "benefits": "Standard benefits",
    "min_years_experience": 3,
    "required_degree": "Bachelor's degree"
  },
  "required_degree": "Bachelor's degree",
  "min_years_experience": 3
}
```

Required fields:

- `job_role`
- `job_description`

Optional override fields:

- `required_degree`
- `min_years_experience`

Response:

```json
{
  "status": true,
  "data": [
    {
      "employee_id": "EMP001",
      "name": "John Doe",
      "title": "Data Scientist",
      "score": 0.85,
      "experience_years": 4,
      "reasons": [
        "Strong SQL skills",
        "Experienced in Python"
      ]
    }
  ],
  "message": "Found 1 matching candidates for Data Analyst"
}
```

### Talent Matcher Health

```http
GET /api/v1/talent_matcher/health
```

Response:

```json
{
  "status": "ok",
  "agent": "Talent Matcher"
}
```

## Candidate Criteria Agent

Extracts platform-specific candidate search criteria from a job description.

### Generate Candidate Criteria

```http
POST /api/v1/criteria/generate
Content-Type: application/json
```

Request body:

```json
{
  "jd_text": "We are hiring a Senior Data Analyst in Mumbai. The ideal candidate has 5+ years of experience with SQL, Python, and Power BI. Responsibilities include creating dashboards and performing statistical analysis.",
  "target": "all"
}
```

Required fields:

- `jd_text`: minimum 50 characters
- `target`: one of `linkedin`, `indeed`, `naukri`, `all`

Response:

```json
{
  "status": true,
  "criteria": {
    "linkedin": {},
    "indeed": {},
    "naukri": {}
  }
}
```

### Criteria Health

```http
GET /api/v1/criteria/health
```

Response:

```json
{
  "status": "ok",
  "agent": "Criteria Agent"
}
```

## Job Post Agent

Creates platform-specific job posts from a job description.

### Generate Job Post

```http
POST /api/v1/job-post-agent/generate
Content-Type: application/json
```

Request body:

```json
{
  "job_description": "We are seeking a Senior Python Developer with strong FastAPI experience, REST API development skills, database knowledge, and experience building production backend services.",
  "platform": "LinkedIn"
}
```

Required fields:

- `job_description`: minimum 50 characters
- `platform`: one of `LinkedIn`, `Indeed`, `Naukri`

Response:

```json
{
  "status": true,
  "platform": "LinkedIn",
  "generated_post": "Generated job post text..."
}
```

## Resume Matcher Agent

Compares a resume file against a job description.

### Match Resume to Job Description

```http
POST /api/v1/resume_matcher/match
Content-Type: multipart/form-data
```

Form fields:

- `job_description`: full job description text or JSON string
- `resume`: resume file; supported extensions are `.pdf`, `.docx`, and `.txt`

Example:

```bash
curl -X POST "http://122.170.2.205:7010/api/v1/resume_matcher/match" \
  -F "job_description=We need a Python developer with FastAPI experience." \
  -F "resume=@/path/to/resume.pdf"
```

Response:

```json
{
  "candidate_name": "John Doe",
  "email": "john.doe@example.com",
  "contact": "+91-9999999999",
  "socials": [
    "https://www.linkedin.com/in/johndoe"
  ],
  "confidence_score": 0.92,
  "skills": [
    "Python",
    "FastAPI"
  ],
  "experience": "4 years of backend development experience",
  "mismatch_reasons": []
}
```

## Question Generator Agent

Generates interview questions from a job description, requirements, and a PDF resume.

### Generate Questionnaire

```http
POST /api/v1/question_generator/generate
Content-Type: multipart/form-data
```

Form fields:

- `jd_text`: full job description text
- `requirements`: one or more requirement values
- `resume_file`: candidate resume PDF file; content type must be `application/pdf`

Example:

```bash
curl -X POST "http://122.170.2.205:7010/api/v1/question_generator/generate" \
  -F "jd_text=We need a Python developer with FastAPI and SQL experience." \
  -F "requirements=Python" \
  -F "requirements=FastAPI" \
  -F "requirements=SQL" \
  -F "resume_file=@/path/to/resume.pdf;type=application/pdf"
```

Response:

```json
{
  "status": true,
  "questions": [
    "Can you explain your experience building APIs with FastAPI?",
    "How have you optimized SQL queries in previous projects?"
  ]
}
```

## Interview Agent

Starts and manages automated Google Meet interview sessions.

### Start Google Meet Interview

```http
POST /api/v1/interview/start-google-meet
Content-Type: multipart/form-data
```

Form fields:

- `meet_link`: Google Meet URL
- `job_role`: job role being interviewed for
- `resume`: candidate resume file; supported extensions are `.pdf`, `.docx`, and `.txt`
- `questionnaire_json`: optional JSON array of question strings
- `audio_device`: optional audio device index
- `enable_video`: optional boolean, defaults to `true`
- `job_description`: optional job description text
- `video_capture_method`: optional value, defaults to `javascript`
- `candidate_email`: candidate email address
- `buss_id`: business identifier associated with the candidate

Example:

```bash
curl -X POST "http://122.170.2.205:7010/api/v1/interview/start-google-meet" \
  -F "meet_link=https://meet.google.com/abc-defg-hij" \
  -F "job_role=Data Analyst" \
  -F "job_description=Analyze business data and build dashboards." \
  -F 'questionnaire_json=["Tell me about your SQL experience.","How do you validate dashboard accuracy?"]' \
  -F "enable_video=true" \
  -F "video_capture_method=javascript" \
  -F "candidate_email=candidate@example.com" \
  -F "buss_id=BUSS-123" \
  -F "resume=@/path/to/resume.pdf"
```

Success response uses HTTP `202 Accepted`:

```json
{
  "status": "pending",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

Possible errors:

- `503`: server interview capacity reached
- `400`: invalid resume or invalid questionnaire JSON
- `500`: interview task scheduling failed

### Retrieve Interview Analysis

Actionabl polls `GET /api/v1/interview/analysis/{buss_id}`. It receives `202`
while the interview is active and `200` with the full final analysis, agent
errors, and terminal reason after a terminal result. An `interrupted` result
with `backend_shutdown` or `backend_restarted` requires Actionabl to schedule a
replacement with a new unique `buss_id`. See the Interview Agent API reference
for the response shape and PostgreSQL setup steps.

### Linux Audio Recovery

On Linux, the application recreates the `BotSpeaker`, `BotMic`, and Chromium
virtual source when PipeWire/PulseAudio restarts. It also checks audio setup
immediately before a new Google Meet session starts. The background recovery
check runs every 15 seconds by default; set
`LINUX_AUDIO_RECOVERY_INTERVAL_SECONDS` to change the interval (minimum 5
seconds).

The PipeWire-Pulse or PulseAudio server must still run under the same Linux user
as PM2. Verify this with `pactl info` after a VM restart.

The interview TTS provider uses `gemini-3.1-flash-tts-preview` with the Gemini
`Kore` voice and English (India) locale. See the Interview Agent API reference
for required Google Cloud permissions, optional model/voice environment
variables, and the TTS-only pronunciation glossary. The glossary makes common
stack names such as `MERN` speak as words while spelling technical acronyms
such as `API` and `SQL`; it can be extended with
`TTS_PRONUNCIATION_OVERRIDES_JSON`.

### Get Interview Status

```http
GET /api/v1/interview/{session_id}/status
```

Response examples:

```json
{
  "status": "completed",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

```json
{
  "status": "active",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

```json
{
  "status": "active_or_not_found",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

### End Interview

```http
POST /api/v1/interview/{session_id}/end
```

Response:

```json
{
  "status": "ending",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

## Example Agent

Template endpoint for testing LLM and database service wiring.

### Query Example Agent

```http
POST /api/v1/example/example-agent/query
Content-Type: application/json
```

Request body:

```json
{
  "query": "Hello",
  "context": "Optional extra context",
  "use_provider": "gemini"
}
```

Response:

```json
{
  "agent_name": "example_agent",
  "result": "Generated response...",
  "provider_used": "gemini"
}
```

### Example Agent Health

```http
GET /api/v1/example/example-agent/health
```

Response:

```json
{
  "success": true,
  "data": {
    "status": "healthy"
  },
  "message": "Success"
}
```

## WebSocket

### Echo WebSocket

```text
ws://122.170.2.205:7010/ws/{client_id}
```

The current implementation accepts text messages and sends back:

```text
Echo: <message>
```

## Error Format

Most endpoints return FastAPI validation errors for invalid input:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": [
        "body",
        "field_name"
      ],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

Several agent endpoints wrap application errors as:

```json
{
  "status": false,
  "detail": "Error message"
}
```

or:

```json
{
  "detail": {
    "status": false,
    "error": "Error message"
  }
}
```
