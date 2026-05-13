import logging
import pymongo
import gridfs
from pymongo.errors import ConnectionFailure
from bson.objectid import ObjectId
from datetime import datetime
from typing import Optional, Dict, Any, List

from app.agents.interview.core.ports.session_repository import SessionRepository
from app.core.config import settings

logger = logging.getLogger(__name__)

class MongoSessionRepository(SessionRepository):
    TRANSCRIPT_BUCKET_SIZE = 50

    def __init__(self):
        mongodb_url = settings.MONGODB_URL
            
        try:
            self.client = pymongo.MongoClient(mongodb_url, serverSelectionTimeoutMS=5000)
            self.db = self.client[settings.DATABASE_NAME]
            self.fs = gridfs.GridFS(self.db)
            
            self.sessions = self.db['sessions']
            self.transcripts = self.db['transcripts']
            self.analyses = self.db['analyses']

            self._init_indexes()
            logger.info("MongoDB Connected (MongoSessionRepository)")
        except ConnectionFailure as e:
            logger.error(f"Could not connect to MongoDB: {e}")
            raise

    def _init_indexes(self):
        self.sessions.create_index([("candidate_id", 1)], background=True)
        self.sessions.create_index([("status", 1)], background=True)
        self.sessions.create_index([("created_at", -1)], background=True)
        self.transcripts.create_index([("session_id", 1), ("bucket_index", 1)], unique=True, background=True)
        self.analyses.create_index([("session_id", 1)], unique=True, background=True)

    # --- Implement Abstract Methods ---

    def save_file(self, filename: str, data: bytes, content_type: str = "audio/wav") -> bool:
        try:
            if self.fs.exists({"filename": filename}):
                return True
            self.fs.put(data, filename=filename, content_type=content_type)
            return True
        except Exception as e:
            logger.error(f"Failed to save file {filename}: {e}")
            return False

    def get_file(self, filename: str) -> Optional[bytes]:
        try:
            grid_out = self.fs.find_one({"filename": filename})
            return grid_out.read() if grid_out else None
        except Exception:
            return None

    def list_files(self, prefix: str) -> List[str]:
        try:
            # Escape regex characters in prefix just in case
            import re
            escaped_prefix = re.escape(prefix)
            regex = f"^{escaped_prefix}"
            
            cursor = self.fs.find({"filename": {"$regex": regex}})
            files = [grid_out.filename for grid_out in cursor]
            return sorted(files)
        except Exception as e:
            logger.error(f"Failed to list files with prefix {prefix}: {e}")
            return []

    def create_session(self, resume_text: str, candidate_id: str, job_role: str, questionnaire: List[str], job_description: Optional[str] = None, webhook_url: Optional[str] = None) -> str:
        session_data = {
            "candidate_id": candidate_id, 
            "resume_text": resume_text,
            "job_role": job_role,
            "job_description": job_description,
            "questionnaire": questionnaire, 
            "webhook_url": webhook_url,
            "created_at": datetime.now(),
            "status": "pending",
            "usage_tracking": {
                "gemini_interview": { "prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0 },
                "gemini_analysis": { "prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0 },
                "stt": { "total_seconds": 0.0 },
                "tts": { "total_characters": 0 }
            }
        }
        result = self.sessions.insert_one(session_data)
        return str(result.inserted_id)

    def add_message_to_session(self, session_id: str, role: str, text: str, audio_path: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None, is_follow_up: bool = False, turn_count: int = 0) -> None:
        if not session_id: return
        try:
            message: Dict[str, Any] = {
                "role": role, "text": text, "timestamp": datetime.now(),
                "is_follow_up": is_follow_up, "turn": turn_count
            }
            if audio_path: message["audio_path"] = audio_path
            if start_time and end_time and role == 'user':
                message["start_timestamp"] = start_time
                message["end_timestamp"] = end_time
            
            bucket_index = turn_count // self.TRANSCRIPT_BUCKET_SIZE
            self.transcripts.update_one(
                {"session_id": ObjectId(session_id), "bucket_index": bucket_index},
                {
                    "$push": {"messages": message},
                    "$min": {"first_turn": turn_count},
                    "$max": {"last_turn": turn_count},
                    "$setOnInsert": {"created_at": datetime.now()} 
                }, upsert=True
            )
        except Exception as e:
            logger.error(f"Error adding message: {e}")

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id or not ObjectId.is_valid(session_id): return None
        return self.sessions.find_one({"_id": ObjectId(session_id)})

    def get_full_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id or not ObjectId.is_valid(session_id): return None
        try:
            pipeline = [
                {"$match": {"_id": ObjectId(session_id)}},
                {"$lookup": {"from": "transcripts", "localField": "_id", "foreignField": "session_id", "pipeline": [{"$sort": {"bucket_index": 1}}], "as": "transcript_buckets"}},
                {"$lookup": {"from": "analyses", "localField": "_id", "foreignField": "session_id", "as": "analysis_docs"}}
            ]
            results = list(self.sessions.aggregate(pipeline))
            if not results: return None
            session = results[0]
            msgs = []
            for bucket in session.get("transcript_buckets", []): msgs.extend(bucket.get("messages", []))
            session["conversation"] = msgs
            if session.get("analysis_docs"):
                adoc = session["analysis_docs"][0]
                adoc.pop('_id', None); adoc.pop('session_id', None)
                session["analysis"] = adoc
            session.pop("transcript_buckets", None); session.pop("analysis_docs", None)
            return session
        except Exception: return None

    def update_session_status(self, session_id: str, status: str):
        if not session_id: return
        self.sessions.update_one({"_id": ObjectId(session_id)}, {"$set": {"status": status}})

    def update_session(self, session_id: str, update_data: Dict[str, Any]) -> bool:
        """
        Update session document with arbitrary fields.
        Used for logging incidents, termination reasons, etc.
        """
        if not session_id:
            return False
        
        try:
            update_data['last_updated_at'] = datetime.now()
            
            result = self.sessions.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": update_data}
            )
            
            return result.modified_count > 0 or result.matched_count > 0
            
        except Exception as e:
            logger.error(f"Failed to update session {session_id}: {e}")
            return False

    def save_checkpoint(self, session_id: str, state_data: Dict[str, Any]):
        if not session_id: return
        self.sessions.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": {"orchestrator_state": state_data, "last_active_at": datetime.now()}}
        )

    def load_checkpoint(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id: return None
        doc = self.sessions.find_one({"_id": ObjectId(session_id)}, {"orchestrator_state": 1})
        return doc.get("orchestrator_state") if doc else None

    def save_analysis_result(self, session_id: str, analysis_data: Dict[str, Any]) -> bool:
        if not session_id: return False
        try:
            analysis_doc = {"session_id": ObjectId(session_id), "updated_at": datetime.now(), "created_at": datetime.now()}
            analysis_doc.update(analysis_data)
            self.analyses.update_one({"session_id": ObjectId(session_id)}, {"$set": analysis_doc}, upsert=True)
            self.sessions.update_one({"_id": ObjectId(session_id)}, {"$set": {"status": "completed", "has_analysis": True}})
            return True
        except Exception: return False

    def get_analysis_report(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id or not ObjectId.is_valid(session_id): return None
        analysis_doc = self.analyses.find_one({"session_id": ObjectId(session_id)})
        if analysis_doc:
            analysis_doc.pop('_id', None); analysis_doc.pop('session_id', None)
            return analysis_doc
        return None

    def get_transcript_text(self, session_id: str) -> Optional[str]:
        if not session_id or not ObjectId.is_valid(session_id): return None
        buckets = list(self.transcripts.find({"session_id": ObjectId(session_id)}).sort("bucket_index", 1))
        lines = []
        for bucket in buckets:
            for msg in bucket.get("messages", []):
                lines.append(f"{msg.get('role', 'u').upper()}: {msg.get('text', '')}")
        return "\n".join(lines)

    # --- NEW METHODS REQUIRED FOR BACKGROUND TASK ---

    def save_transcript_text(self, session_id: str, transcript_text: str) -> bool:
        """
        Saves the raw text transcript to the session document for fallback/analysis.
        """
        if not session_id: return False
        try:
            self.sessions.update_one(
                {"_id": ObjectId(session_id)}, 
                {"$set": {"transcript_text": transcript_text, "updated_at": datetime.now()}}
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save transcript text: {e}")
            return False

    def mark_analysis_pending(self, session_id: str):
        """Marks the session status as analysis_pending."""
        self.update_session_status(session_id, "analysis_pending")

    # --- USAGE TRACKING ---

    def update_gemini_token_usage(self, session_id: str, usage_type: str, p: int, r: int, t: int):
        if not session_id: return
        prefix = f"usage_tracking.gemini_{usage_type}"
        self.sessions.update_one({"_id": ObjectId(session_id)}, {"$inc": {f"{prefix}.prompt_tokens": p, f"{prefix}.response_tokens": r, f"{prefix}.total_tokens": t}})

    def update_tts_character_usage(self, session_id: str, count: int):
        if not session_id: return
        self.sessions.update_one({"_id": ObjectId(session_id)}, {"$inc": {"usage_tracking.tts.total_characters": count}})

    def update_stt_usage(self, session_id: str, seconds: float):
        if not session_id: return
        self.sessions.update_one({"_id": ObjectId(session_id)}, {"$inc": {"usage_tracking.stt.total_seconds": seconds}})

    def check_connection(self) -> bool:
        try:
            self.client.admin.command('ping')
            return True
        except Exception: return False
