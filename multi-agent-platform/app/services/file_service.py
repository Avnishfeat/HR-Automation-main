from fastapi import UploadFile
import aiofiles
import os
from pathlib import Path
from typing import Optional
import uuid
import logging

logger = logging.getLogger(__name__)

class FileService:
    """File handling service"""
    
    def __init__(self, upload_dir: str = "./uploads"):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
    
    async def save_file(
        self, 
        file: UploadFile, 
        subfolder: Optional[str] = None
    ) -> dict:
        """
        Save uploaded file
        
        Returns:
            dict with file_path, filename, size
        """
        # Create unique filename
        file_ext = Path(file.filename).suffix
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        
        # Determine save path
        if subfolder:
            save_dir = self.upload_dir / subfolder
            save_dir.mkdir(parents=True, exist_ok=True)
        else:
            save_dir = self.upload_dir
        
        file_path = save_dir / unique_filename
        
        # Save file
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        return {
            "file_path": str(file_path),
            "filename": unique_filename,
            "original_filename": file.filename,
            "size": len(content)
        }
    
    async def read_file(self, file_path: str) -> bytes:
        """Read file content"""
        async with aiofiles.open(file_path, 'rb') as f:
            return await f.read()
    
    def delete_file(self, file_path: str) -> bool:
        """Delete file"""
        try:
            os.remove(file_path)
            return True
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False
