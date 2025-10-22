import re
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from app.agents.talent_matcher.loader import load_employees 

class TalentMatcherService:
    def __init__(self):
        """
        Initializes the service, loads employee data, and pre-computes
        all employee profile embeddings for performance.
        """
        # 1. Initialize the model
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.employees = load_employees("data/employees.jsonl")
        
        # 2. Pre-process employee data
        all_profile_texts = []
        for i, emp in enumerate(self.employees):
            # Add a unique STRING ID to satisfy the response schema
            emp["Employee_ID"] = str(i + 1)
            
            # Combine relevant fields into a single string for embedding
            profile_text = f"{emp.get('title', '')} {', '.join(emp.get('skills', []))} {emp.get('Key_Credentials', '')}"
            all_profile_texts.append(profile_text)

        # 3. Pre-compute all employee embeddings in a single batch operation (very fast)
        self.employee_embeddings = self.model.encode(all_profile_texts, show_progress_bar=False)
        print("✅ Employee profiles pre-computed successfully.")

    def _extract_degree_from_jd(self, job_description) -> str:
        """
        Extracts degree requirement from job description.
        Looks in minimum_qualification field.
        """
        qualification = job_description.minimum_qualification.lower()
        
        # Check for common degree types
        if "master" in qualification or "m.s." in qualification or "msc" in qualification:
            return "Master"
        elif "bachelor" in qualification or "b.s." in qualification or "bsc" in qualification or "b.tech" in qualification:
            return "Bachelor"
        elif "phd" in qualification or "doctorate" in qualification:
            return "PhD"
        
        return "Bachelor"  # Default fallback

    def _extract_experience_from_jd(self, job_description) -> int:
        """
        Extracts minimum years of experience from job description.
        Looks in key_skills_and_qualifications and overview fields.
        """
        # Combine relevant fields
        text = f"{job_description.key_skills_and_qualifications} {job_description.overview}".lower()
        
        # Look for patterns like "5+ years", "5 years", "minimum of 5 years"
        patterns = [
            r'minimum\s+of\s+(\d+)\s*\+?\s*years',
            r'(\d+)\s*\+\s*years',
            r'(\d+)\s+years',
            r'at least\s+(\d+)\s*years'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        
        return 0  # Default to 0 if no experience specified

    def _create_comprehensive_jd_text(self, job_description) -> str:
        """
        Creates a comprehensive text representation of the job description
        for embedding and matching.
        """
        return f"""
        {job_description.overview}
        
        Required Skills: {job_description.required_skills}
        Preferred Skills: {job_description.preferred_skills}
        Key Responsibilities: {job_description.key_responsibilities}
        Key Skills and Qualifications: {job_description.key_skills_and_qualifications}
        Languages: {job_description.languages}
        Desired Attributes: {job_description.desired_attributes}
        """

    def match(self, request):
        """
        Matches employees to the job description from JD Agent.
        """
        # Extract or use provided matching criteria
        required_degree = request.required_degree or self._extract_degree_from_jd(request.job_description)
        min_experience = request.min_years_experience if request.min_years_experience is not None else self._extract_experience_from_jd(request.job_description)
        
        print(f"📋 Matching criteria: Degree={required_degree}, Experience={min_experience}+ years")
        
        # STEP 1: Filter by degree and experience first
        filtered_indices = [
            i for i, emp in enumerate(self.employees)
            if required_degree in emp.get("Key_Credentials", "")
            and emp.get("experience_years", 0) >= min_experience
        ]

        if not filtered_indices:
            print("⚠️ No candidates match the basic criteria")
            return []

        # Get the corresponding filtered employees and their pre-computed embeddings
        filtered_employees = [self.employees[i] for i in filtered_indices]
        filtered_embeddings = self.employee_embeddings[filtered_indices]

        # STEP 2: Create comprehensive job description text and encode it
        jd_text = self._create_comprehensive_jd_text(request.job_description)
        job_embedding = self.model.encode(jd_text)

        # STEP 3: Calculate cosine similarity against all filtered candidates at once
        scores = cosine_similarity([job_embedding], filtered_embeddings)[0]

        # STEP 4: Build the results
        results = []
        for i, emp in enumerate(filtered_employees):
            profile_text = f"{emp.get('title', '')} {', '.join(emp.get('skills', []))} {emp.get('Key_Credentials', '')}"
            results.append({
                "employee_id": emp["Employee_ID"],
                "name": emp.get("name", "N/A"),
                "title": emp.get("title", "N/A"),
                "score": float(scores[i]),
                "experience_years": emp.get("experience_years", 0),
                "reasons": self._extract_reasons(jd_text, profile_text, request.job_description)
            })

        # STEP 5: Sort by score and return the top 5
        results.sort(key=lambda x: x["score"], reverse=True)
        print(f"✅ Found {len(results)} matches, returning top 5")
        return results[:5]

    def _extract_reasons(self, jd: str, profile: str, job_description):
        """
        Extract overlapping keywords with enhanced logic to include
        specific skills from the job description.
        """
        # Get required skills as individual keywords
        required_skills = job_description.required_skills.lower()
        languages = job_description.languages.lower()
        
        # Combine and clean
        jd_keywords = set(word.lower().strip(',.:;') for word in jd.split() if len(word) > 3)
        profile_keywords = set(word.lower().strip(',.:;') for word in profile.split() if len(word) > 3)
        
        # Find overlaps
        overlaps = jd_keywords & profile_keywords
        
        # Filter to most relevant (limit to 5-7 key reasons)
        important_keywords = ['python', 'sql', 'power', 'data', 'analysis', 'excel', 
                            'tableau', 'visualization', 'machine', 'learning', 'aws', 
                            'azure', 'cloud', 'java', 'javascript', 'react', 'node']
        
        relevant_reasons = [kw for kw in overlaps if kw in important_keywords]
        other_reasons = [kw for kw in overlaps if kw not in important_keywords]
        
        # Prioritize important keywords and limit total
        return sorted(relevant_reasons)[:5] + sorted(other_reasons)[:2]