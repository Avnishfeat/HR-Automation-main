import logging
import gridfs
from bson.objectid import ObjectId
from datetime import datetime
from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

# Imports
from app.core.config import settings
from app.core.ports.session_repository import SessionRepository
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)

class MongoSessionRepository(SessionRepository):
    TRANSCRIPT_BUCKET_SIZE = 50

    def __init__(self, db_name: str = "ai_interviewer_db"):
        # We assume DatabaseService is already connected via main.py startup
        self.db = DatabaseService.get_database(db_name)
        
        self.sessions = self.db['sessions']
        self.transcripts = self.db['transcripts']
        self.analyses = self.db['analyses']
        
        # GridFS for audio files
        self.fs = AsyncIOMotorGridFSBucket(self.db)

    async def _init_indexes(self):
        """Call this explicitly or via startup hook if needed."""
        await self.sessions.create_index([("candidate_id", 1)], background=True)
        await self.sessions.create_index([("status", 1)], background=True)
        await self.sessions.create_index([("created_at", -1)], background=True)
        await self.transcripts.create_index([("session_id", 1), ("bucket_index", 1)], unique=True, background=True)
        await self.analyses.create_index([("session_id", 1)], unique=True, background=True)

    # --- File Storage (Async) ---

    async def save_file(self, filename: str, data: bytes, content_type: str = "audio/wav") -> bool:
        try:
            # Check overlap - complicated in GridFSBucket, usually just write new
            # Using specific ID based on filename or just upload
            await self.fs.upload_from_stream(
                filename, 
                data, 
                metadata={"contentType": content_type, "filename": filename}
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save file {filename}: {e}")
            return False

    async def get_file(self, filename: str) -> Optional[bytes]:
        try:
            # GridFSBucket download
            # We need to find the file ID first or open by name
            cursor = self.fs.find({"filename": filename}).sort("uploadDate", -1).limit(1)
            files = await cursor.to_list(length=1)
            if not files:
                return None
            
            file_id = files[0]["_id"]
            # Read into memory (careful with large files)
            grid_out = await self.fs.open_download_stream(file_id)
            return await grid_out.read()
        except Exception:
            return None

    # --- Session Management ---

    async def create_session(self, session_data: Dict) -> str:
        # Compatibility wrapper: if passed dict, insert it. 
        # If passed args, method overloading (not pythonic) or separate method.
        # The base interface expects Dict, but original had separate args.
        # We'll stick to the interface signature for the override.
        
        # Ensure timestamp
        if "created_at" not in session_data:
            session_data["created_at"] = datetime.now()
        
        result = await self.sessions.insert_one(session_data)
        return str(result.inserted_id)

    # Original signature helper (can be used by service)
    async def create_new_session(self, resume_text: str, candidate_id: str, job_role: str, questionnaire: List[str], job_description: Optional[str] = None) -> str:
        session_data = {
            "candidate_id": candidate_id, 
            "resume_text": resume_text,
            "job_role": job_role,
            "job_description": job_description,
            "questionnaire": questionnaire, 
            "created_at": datetime.now(),
            "status": "pending",
            "usage_tracking": {
                "gemini_interview": { "prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0 },
                "gemini_analysis": { "prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0 },
                "stt": { "total_seconds": 0.0 },
                "tts": { "total_characters": 0 }
            }
        }
        return await self.create_session(session_data)

    async def add_message_to_session(self, session_id: str, role: str, text: str, audio_path: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None, is_follow_up: bool = False, turn_count: int = 0) -> None:
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
            await self.transcripts.update_one(
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

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id or not ObjectId.is_valid(session_id): return None
        return await self.sessions.find_one({"_id": ObjectId(session_id)})

    async def get_full_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id or not ObjectId.is_valid(session_id): return None
        try:
            pipeline = [
                {"$match": {"_id": ObjectId(session_id)}},
                {"$lookup": {"from": "transcripts", "localField": "_id", "foreignField": "session_id", "pipeline": [{"$sort": {"bucket_index": 1}}], "as": "transcript_buckets"}},
                {"$lookup": {"from": "analyses", "localField": "_id", "foreignField": "session_id", "as": "analysis_docs"}}
            ]
            cursor = self.sessions.aggregate(pipeline)
            results = await cursor.to_list(length=1)
            
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

    async def update_session_status(self, session_id: str, status: str) -> bool:
        if not session_id: return False
        result = await self.sessions.update_one({"_id": ObjectId(session_id)}, {"$set": {"status": status}})
        return result.modified_count > 0

    async def update_session(self, session_id: str, update_data: Dict[str, Any]) -> bool:
        if not session_id: return False
        try:
            update_data['last_updated_at'] = datetime.now()
            result = await self.sessions.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": update_data}
            )
            return result.modified_count > 0 or result.matched_count > 0
        except Exception as e:
            logger.error(f"Failed to update session {session_id}: {e}")
            return False

    async def add_turn(self, session_id: str, turn_data: Dict) -> bool:
        # Interface implementation - simplified wrapper around add_message_to_session or direct update
        # For now, just a placeholder if not strictly used or we can map it
        return False

    async def get_active_sessions(self) -> List[Dict]:
        cursor = self.sessions.find({"status": {"$in": ["active", "active_scheduled"]}})
        return await cursor.to_list(length=100)

    async def save_checkpoint(self, session_id: str, state_data: Dict[str, Any]):
        if not session_id: return
        await self.sessions.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": {"orchestrator_state": state_data, "last_active_at": datetime.now()}}
        )

    async def load_checkpoint(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id: return None
        doc = await self.sessions.find_one({"_id": ObjectId(session_id)}, {"orchestrator_state": 1})
        return doc.get("orchestrator_state") if doc else None

    async def save_analysis_result(self, session_id: str, analysis_data: Dict[str, Any]) -> bool:
        if not session_id: return False
        try:
            analysis_doc = {"session_id": ObjectId(session_id), "updated_at": datetime.now(), "created_at": datetime.now()}
            analysis_doc.update(analysis_data)
            await self.analyses.update_one({"session_id": ObjectId(session_id)}, {"$set": analysis_doc}, upsert=True)
            await self.sessions.update_one({"_id": ObjectId(session_id)}, {"$set": {"status": "completed", "has_analysis": True}})
            return True
        except Exception: return False

    async def get_analysis_report(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id or not ObjectId.is_valid(session_id): return None
        analysis_doc = await self.analyses.find_one({"session_id": ObjectId(session_id)})
        if analysis_doc:
            analysis_doc.pop('_id', None); analysis_doc.pop('session_id', None)
            return analysis_doc
        return None

    async def get_transcript_text(self, session_id: str) -> Optional[str]:
        if not session_id or not ObjectId.is_valid(session_id): return None
        cursor = self.transcripts.find({"session_id": ObjectId(session_id)}).sort("bucket_index", 1)
        buckets = await cursor.to_list(length=None)
        lines = []
        for bucket in buckets:
            for msg in bucket.get("messages", []):
                lines.append(f"{msg.get('role', 'u').upper()}: {msg.get('text', '')}")
        return "\n".join(lines)

    async def save_transcript_text(self, session_id: str, transcript_text: str) -> bool:
        if not session_id: return False
        try:
            await self.sessions.update_one(
                {"_id": ObjectId(session_id)}, 
                {"$set": {"transcript_text": transcript_text, "updated_at": datetime.now()}}
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save transcript text: {e}")
            return False

    async def mark_analysis_pending(self, session_id: str):
        await self.update_session_status(session_id, "analysis_pending")

    # --- USAGE TRACKING ---

    async def update_gemini_token_usage(self, session_id: str, usage_type: str, p: int, r: int, t: int):
        if not session_id: return
        prefix = f"usage_tracking.gemini_{usage_type}"
        await self.sessions.update_one({"_id": ObjectId(session_id)}, {"$inc": {f"{prefix}.prompt_tokens": p, f"{prefix}.response_tokens": r, f"{prefix}.total_tokens": t}})

    async def update_tts_character_usage(self, session_id: str, count: int):
        if not session_id: return
        await self.sessions.update_one({"_id": ObjectId(session_id)}, {"$inc": {"usage_tracking.tts.total_characters": count}})

    async def update_stt_usage(self, session_id: str, seconds: float):
        if not session_id: return
        await self.sessions.update_one({"_id": ObjectId(session_id)}, {"$inc": {"usage_tracking.stt.total_seconds": seconds}})

    async def check_connection(self) -> bool:
        try:
            # Reusing DatabaseService client
            await DatabaseService.client.admin.command('ping')
            return True
        except Exception: return False
