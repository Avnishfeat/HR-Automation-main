Generate an api from gemini from this website https://aistudio.google.com

after generating api create a file name .env and paste the api in this format
#GEMINI_API_KEY="Your API Key"
make sure you dont share your api key with any one

create your virtual environment using this command
python -m venv venv

and activat the enironment using this command
.\venv\Scripts\Activate.ps1
or 
.'venv\Scripts\activate

install required libraries using requirement.txt  file
pip install -r requirements,txt

and run this command in terminal
uvicorn app.main:app --reload

after starting uvicorn server you will get the port address paste the address in the cutl code 
example"http://127.0.0.1:8000"

1. Download Postman application from their website https://www.postman.com/
2. Setup Postman
3. select code snippet and paste the curl code and send the request

if the port is different then change it

for job_description agent:-

curl -X POST 'http://127.0.0.1:8000/api/v1/jd/generate' \
-H "Content-Type: application/json" \
-d '{
   "job_role": "your job role",
  "experience": "experience in years",
  "requirements": "skill requirements"
}'

example:{
  "job_role": "Data Analyst",
  "experience": "3+ years",
  "requirements": "SQL, Python, Power BI"
}

for talent_matcher agent:

curl --location 'http://localhost:8000/api/v1/talent_matcher/match-job' \
--header 'Content-Type: application/json' \
--data '{
  "job_description": "your job description",
  "required_degree": "degree",
  "min_years_experience": "experience in years"
}'
"""
example:
{
  "job_description": "Seeking a senior data scientist with a strong background in statistical analysis and building machine learning models using Python, Pandas, and Scikit-learn.",
  "required_degree": "PhD",
  "min_years_experience": 10
}
"""

for criteria_agent:

curl --location 'http://127.0.0.1:8000/api/v1/criteria/generate' \
--header 'Content-Type: application/json' \
--data '{
  "jd_text": "your job description",
  "target": "applications like linkedin"
}'
"""
example:
{
  "jd_text": "We are hiring a Senior Data Analyst in Mumbai. The ideal candidate has 5+ years of experience with SQL, Python, and Power BI. Responsibilities include creating dashboards and performing statistical analysis.",
  "target": "all"
}
"""
# its only of linkedin, indeed, and naukri

for job_post_agent:

curl --location 'http://127.0.0.1:8000/api/v1/job-post-agent/generate' \
--header 'Content-Type: application/json' \
--data '{
  "job_description": "your job description",
  "platform": "application name"
}'
"""
example:
{
  "job_description": "We are seeking a Senior Python Developer to join our backend team. The successful candidate will be responsible for designing, building, and maintaining scalable server-side applications and APIs. Key responsibilities include writing clean, efficient code using frameworks like Django or FastAPI, managing database schemas in PostgreSQL, and deploying services on cloud platforms like AWS. Requires 5+ years of professional Python experience and strong problem-solving skills.",
  "platform": "Indeed"
}
"""
# its only of linkedin, indeed, and naukri