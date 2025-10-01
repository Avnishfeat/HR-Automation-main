class JobPostAgentService:
    def __init__(self, llm_service):
        self.llm_service = llm_service
        self.prompt_templates = {
            "LinkedIn": """
            Create a professional, engaging, and enthusiastic job post for LinkedIn...
            **Important: Do not include any introductory phrases...**
            --- Job Description ---
            {job_description}
            """,
            "Indeed": """
            Generate a clear, direct, and well-structured job post for Indeed...
            **Important: Do not include any introductory phrases...**
            --- Job Description ---
            {job_description}
            """,
            "Naukri": """
            Draft a detailed and comprehensive job post for Naukri.com...
            **Important: Do not include any introductory phrases...**
            --- Job Description ---
            {job_description}
            """
        }

    async def generate_post(self, platform: str, job_description: str) -> dict:
        template = self.prompt_templates.get(platform)
        if not template:
            raise ValueError("Invalid platform specified.")

        prompt = template.format(job_description=job_description)
        
        # --- CRITICAL CHANGE ---
        # Call the correct method from your LLMService ('generate_text')
        # and pass only the prompt.
        response_text = await self.llm_service.generate_text(prompt=prompt)
        # --------------------
        
        return {"result": response_text}