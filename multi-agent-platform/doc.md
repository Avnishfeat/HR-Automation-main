# API Documentation - Multi-Agent Platform

This document provides detailed information about the available APIs in the Multi-Agent Platform.

**Base URL:** `http://122.170.2.205:8048`  
**Swagger Docs:** `http://122.170.2.205:8048/docs`

---

## 1. Job Description (JD) Agent
Generates structured job descriptions based on role, requirements, and experience.

### Generate JD (Standard)
- **URL:** `/api/v1/jd/generate`
- **Method:** `POST`
- **Description:** Generates a JD optimized for the Talent Matcher Agent.
- **Request Body:**
```json
{
  "job_role": "Data Analyst",
  "requirements": "SQL, Python, Power BI",
  "experience_range": "3-5 years",
  "work_location": "Mumbai",
  "job_type": "Full-time"
}
```
- **Response:**
```json
{
  "status": true,
  "job_role": "Data Analyst",
  "job_description": {
    "required_skills": "...",
    "preferred_skills": "...",
    "minimum_qualification": "...",
    "languages": "...",
    "overview": "...",
    "key_responsibilities": "...",
    "key_skills_and_qualifications": "...",
    "desired_attributes": "...",
    "benefits": "..."
  }
}
```

### Generate JD (Flat)
- **URL:** `/api/v1/jd/generate-flat`
- **Method:** `POST`
- **Description:** Returns a flat structure of the job description.

---

## 2. Talent Matcher Agent
Matches employees to a given job description.

### Match Employees
- **URL:** `/api/v1/talent_matcher/match-job`
- **Method:** `POST`
- **Description:** Matches employee profiles against a structured JD.
- **Request Body:**
```json
{
  "job_role": "Data Analyst",
  "job_description": {
    "required_skills": "SQL, Python, Power BI",
    "minimum_qualification": "Bachelor's Degree",
    "min_years_experience": 3
  }
}
```
- **Response:**
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
      "reasons": ["Strong SQL skills", "Experienced in Python"]
    }
  ],
  "message": "Found 1 matching candidates for Data Analyst"
}
```

---

## 3. Candidate Criteria Agent
Extracts search criteria for various platforms from a JD.

### Generate Criteria
- **URL:** `/api/v1/criteria/generate`
- **Method:** `POST`
- **Request Body:**
```json
{
  "jd_text": "We are hiring a Senior Data Analyst in Mumbai...",
  "target": "all" 
}
```
- **Targets:** `linkedin`, `indeed`, `naukri`, `all`
- **Response:**
```json
{
  "status": true,
  "criteria": {
    "linkedin": { ... },
    "indeed": { ... },
    "naukri": { ... }
  }
}
```

---

## 4. Job Post Agent
Creates platform-specific job posts from a JD.

### Generate Job Post
- **URL:** `/api/v1/job-post-agent/generate`
- **Method:** `POST`
- **Request Body:**
```json
{
  "job_description": "We are seeking a Senior Python Developer...",
  "platform": "LinkedIn"
}
```
- **Platforms:** `LinkedIn`, `Indeed`, `Naukri`
- **Response:**
```json
{
  "status": true,
  "platform": "LinkedIn",
  "generated_post": "..."
}
```

---

## 5. Resume Matcher Agent
Compares a resume (file) against a job description.

### Match Resume to JD
- **URL:** `/api/v1/resume_matcher/match`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`
- **Form Fields:**
  - `job_description`: (String) The JD text or JSON
  - `resume`: (File) The resume (PDF, DOCX, TXT)
- **Response:**
```json
{
  "candidate_name": "John Doe",
  "email": "john.doe@example.com",
  "confidence_score": 0.92,
  "skills": ["Python", "FastAPI"],
  "mismatch_reasons": []
}
```

---

## 6. Question Generator Agent
Generates an interview questionnaire based on JD and Resume.

### Generate Questionnaire
- **URL:** `/api/v1/question_generator/generate`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`
- **Form Fields:**
  - `jd_text`: (String) Job description text
  - `requirements`: (List[String]) Specific requirements
  - `resume_file`: (File) Candidate's resume (PDF)
- **Response:**
```json
{
  "status": true,
  "questions": [
    "Can you explain your experience with SQL?",
    "How have you used Python for data analysis?"
  ]
}
```

---

## 7. Interview Agent
Orchestrates automated interviews via Google Meet.

### Start Google Meet Interview
- **URL:** `/api/v1/interview/start-google-meet`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`
- **Form Fields:**
  - `candidate_id`: "CAND123"
  - `meet_link`: "https://meet.google.com/..."
  - `job_role`: "Data Analyst"
  - `resume`: (File)
  - `questionnaire_json`: (Optional JSON list of questions)
- **Response:**
```json
{
  "status": "pending",
  "session_id": "sess_20260511_123456"
}
```

### Get Interview Status
- **URL:** `/api/v1/interview/{session_id}/status`
- **Method:** `GET`

### End Interview
- **URL:** `/api/v1/interview/{session_id}/end`
- **Method:** `POST`

---

## 8. Example Agent
Template agent for testing purposes.

### Query
- **URL:** `/api/v1/example/example-agent/query`
- **Method:** `POST`
- **Request Body:**
```json
{
  "query": "Hello",
  "use_provider": "gemini"
}
```

---

## Health Checks
All agents have a `/health` endpoint:
- `GET /api/v1/jd/health`
- `GET /api/v1/criteria/health`
- `GET /api/v1/talent_matcher/health`
- `GET /api/v1/example/example-agent/health`
