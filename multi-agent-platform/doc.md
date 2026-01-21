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
}'
"""
example:
{
  "job_role": "Data Analyst",
    "job_description": {
        "required_skills": "Proficiency in SQL for data extraction, manipulation, and optimization. Strong programming skills in Python for data analysis, scripting, and automation. Expertise in Power BI for developing and maintaining interactive dashboards, reports, and data visualizations. Solid understanding of data modeling, data warehousing concepts, and ETL processes.",
        "preferred_skills": "Experience with other data visualization tools such as Tableau or Qlik Sense. Knowledge of statistical analysis, machine learning concepts, and predictive modeling techniques. Familiarity with cloud data platforms (e.g., AWS, Azure, GCP) and big data technologies. Experience with version control systems like Git.",
        "minimum_qualification": "Bachelor's degree in Computer Science, Statistics, Mathematics, Economics, Business Analytics, or a related quantitative field. A minimum of 3 years of professional experience in a data analyst, business intelligence analyst, or similar role.",
        "languages": "English (Fluent)",
        "overview": "We are seeking a highly skilled and experienced Data Analyst with 3+ years of experience to join our dynamic team. The ideal candidate will be instrumental in transforming complex datasets into actionable business insights through robust data visualization and comprehensive reporting, directly supporting strategic decision-making and operational improvements across the organization.",
        "key_responsibilities": "Develop, design, and maintain interactive dashboards and reports using Power BI to visualize key performance indicators, trends, and business metrics. Extract, transform, and load (ETL) data from various databases and data sources using SQL and Python, ensuring data accuracy, consistency, and integrity. Conduct in-depth data analysis to identify patterns, anomalies, root causes, and opportunities for business optimization and growth. Collaborate closely with stakeholders across different departments to understand business requirements and translate them into effective data solutions and analytical deliverables. Present findings, insights, and strategic recommendations to both technical and non-technical audiences clearly and concisely. Contribute to the continuous improvement of data analysis methodologies, tools, and best practices.",
        "key_skills_and_qualifications": "Proven ability to analyze large, complex datasets and translate raw data into clear, concise, and actionable insights. Excellent analytical, problem-solving, and critical thinking skills with a strong attention to detail. Exceptional communication and presentation skills, with the capability to articulate technical information to diverse audiences effectively. Demonstrated experience in creating compelling and user-friendly data visualizations and comprehensive analytical reports. A minimum of 3 years of hands-on professional experience as a Data Analyst, focusing on business intelligence and reporting.",
        "desired_attributes": "A proactive, self-motivated individual with a strong business acumen and a passion for leveraging data to drive decision-making. Ability to work both independently and collaboratively within a fast-paced, evolving environment. Intellectual curiosity, a commitment to continuous learning, and adaptability to new technologies and methodologies.",
        "benefits": "Competitive salary, comprehensive health, dental, and vision insurance plans, paid time off, 401(k) retirement savings plan with company match, professional development opportunities, and a collaborative and innovative work environment."
        }
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