# AI Recruitment Agent Suite

A FastAPI-powered backend utilizing the Gemini API to automate Job Description (JD) generation, talent matching, screening criteria, and platform-specific job postings.

## Prerequisites

1. **Get Gemini API Key:**
* Visit [Google AI Studio](https://aistudio.google.com).
* Generate your API key.


2. **Install Postman:**
* Download and install from [Postman.com](https://www.postman.com/).



## Setup Instructions

### 1. Environment Configuration

Create a file named `.env` in the root directory and paste your API key:

```env
# .env file
GEMINI_API_KEY="Your_API_Key_Here"

```

> **Security Note:** Do not share your API key or commit your `.env` file to public repositories.

### 2. Virtual Environment Setup

Run the following commands in your terminal to isolate your dependencies:

```bash
# Create the environment
python -m venv venv

# Activate the environment (Windows)
.\venv\Scripts\Activate.ps1
# OR
.\venv\Scripts\activate

```

### 3. Installation & Launch

```bash
# Install required libraries
pip install -r requirements.txt

# Start the Uvicorn server
uvicorn app.main:app --reload

```

Once started, note the address (usually `http://127.0.0.1:8000`).

---

## API Endpoints & Testing

### 1. Job Description Agent

**Endpoint:** `POST /api/v1/jd/generate`

```bash
curl -X POST 'http://127.0.0.1:8000/api/v1/jd/generate' \
-H "Content-Type: application/json" \
-d '{
   "job_role": "Data Analyst",
   "experience": "3+ years",
   "requirements": "SQL, Python, Power BI"
}'

```

### 2. Talent Matcher Agent

**Endpoint:** `POST /api/v1/talent_matcher/match-job`

```bash
curl --location 'http://127.0.0.1:8000/api/v1/talent_matcher/match-job' \
--header 'Content-Type: application/json' \
--data '{
  "job_role": "your job role",
    "job_description": "your job description",
      "required_skills": "required skills",
      "preferred_skills": "preferred skills",
      "minimum_qualification": "minimum qualification",
      "languages": "languages",
      "overview": "overview",
      "key_responsibilities": "key responsibilities",
      "key_skills_and_qualifications": "key skills and qualifications",
      "desired_attributes": "desired attributes",
      "benefits": "benefits"
  }
}'

```

### 3. Criteria Agent

Generates screening questions for specific platforms.
*Supports: `linkedin`, `indeed`, `naukri`, or `all`.*

**Endpoint:** `POST /api/v1/criteria/generate`

```bash
curl --location 'http://127.0.0.1:8000/api/v1/criteria/generate' \
--header 'Content-Type: application/json' \
--data '{
  "jd_text": "Hiring a Senior Data Analyst in Mumbai. 5+ years experience with SQL, Python.",
  "target": "linkedin"
}'

```

### 4. Job Post Agent

Formats JDs for social/professional platform posting.
*Supports: `LinkedIn`, `Indeed`, `Naukri`.*

**Endpoint:** `POST /api/v1/job-post-agent/generate`

```bash
curl --location 'http://127.0.0.1:8000/api/v1/job-post-agent/generate' \
--header 'Content-Type: application/json' \
--data '{
  "job_description": "We are seeking a Senior Python Developer... 5+ years experience.",
  "platform": "Indeed"
}'

```

---

## Testing with Postman

1. Open **Postman**.
2. Click **Import** and paste the `curl` code from above.
3. Ensure the URL matches your local port (`8000` by default).
4. Click **Send** to view the AI-generated response.

---
