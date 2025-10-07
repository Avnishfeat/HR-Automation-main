from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.services.database import DatabaseService


from app.agents.jd_agent.router import router as jd_router
from app.agents.example_agent.router import router as example_agent_router
from app.agents.criteria_agent.router import router as criteria_router
from app.agents.job_post_agent.router import router as job_post_agent_router
from app.agents.talent_matcher.router import router as talent_matcher_router
from app.agents.interview_analysis.router import router as analysis_router
from app.agents.hr_interview_analysis.router import router as hr_analysis_router

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting Multi-Agent Platform...")
    await DatabaseService.connect_db(settings.MONGODB_URL)
    logger.info("✅ Application started successfully")
    yield
    logger.info("🛑 Shutting down...")
    await DatabaseService.close_db()
    logger.info("✅ Application shut down successfully")

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(example_agent_router, prefix="/api/v1/example", tags=["Example Agent"])
app.include_router(jd_router, prefix="/api/v1/jd", tags=["Job Description Agent"])
app.include_router(criteria_router, prefix="/api/v1/criteria", tags=["Candidate Criteria Agent"])
app.include_router(job_post_agent_router,prefix="/api/v1", tags=["Job Post Agent"])
app.include_router(talent_matcher_router,prefix="/api/v1/talent_matcher", tags=["Talent Matcher Agent"])
app.include_router(analysis_router,prefix="/api/v1", tags=["Interview Analysis Agent"])
app.include_router(hr_analysis_router, prefix="/api/v1", tags=["HR Interview Analysis Agent"])


@app.get("/")
async def root():
    return {"message": "Multi-Agent Platform API", "version": settings.APP_VERSION, "docs": "/docs"}