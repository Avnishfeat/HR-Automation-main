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


    def match(self, request):
        # STEP 1: Filter by degree and experience first
        # This narrows down the list of candidates before doing expensive calculations
        filtered_indices = [
            i for i, emp in enumerate(self.employees)
            if request.required_degree in emp.get("Key_Credentials", "")
            and emp.get("experience_years", 0) >= request.min_years_experience
        ]

        if not filtered_indices:
            return [] # Return early if no candidates match the basic criteria

        # Get the corresponding filtered employees and their pre-computed embeddings
        filtered_employees = [self.employees[i] for i in filtered_indices]
        filtered_embeddings = self.employee_embeddings[filtered_indices]

        # STEP 2: Encode the job description
        job_embedding = self.model.encode(request.job_description)

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
                "reasons": self._extract_reasons(request.job_description, profile_text)
            })

        # STEP 5: Sort by score and return the top 5
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:5]

    def _extract_reasons(self, jd: str, profile: str):
        """Extract overlapping keywords (simple heuristic)."""
        jd_keywords = set(word.lower() for word in jd.split())
        profile_keywords = set(word.lower() for word in profile.split())
        return sorted(list(jd_keywords & profile_keywords))