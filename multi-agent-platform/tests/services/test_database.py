# File: tests/services/test_database.py

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.database import DatabaseService

@pytest.mark.asyncio
async def test_connect_db_fails():
    """Tests that the exception during connection is re-raised."""
    mock_client = MagicMock()
    mock_client.admin.command = AsyncMock(side_effect=Exception("Connection failed"))
    
    with patch("app.services.database.AsyncIOMotorClient", return_value=mock_client):
        with pytest.raises(Exception):
            await DatabaseService.connect_db("mongodb://fake")
            
    DatabaseService.client = None

@pytest.mark.asyncio
async def test_close_db_success():
    """Tests the successful path for closing the DB connection."""
    mock_client = MagicMock()
    DatabaseService.client = mock_client
    
    await DatabaseService.close_db()
    
    mock_client.close.assert_called_once()
    DatabaseService.client = None

@pytest.mark.asyncio
async def test_close_db_not_connected():
    """Tests that calling close_db when client is None does nothing."""
    DatabaseService.client = None
    await DatabaseService.close_db()

def test_get_database_not_connected():
    """Tests that getting a DB before connecting raises an exception."""
    DatabaseService.client = None 
    with pytest.raises(Exception, match="Database not connected"):
        DatabaseService.get_database("test_db")

# --- NEW TEST TO COVER 1 MISSING LINE ---
def test_get_database_success():
    """Tests the success path for get_database."""
    # Arrange
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    DatabaseService.client = mock_client
    
    # Act
    db = DatabaseService.get_database("test_db")
    
    # Assert
    assert db is mock_db
    mock_client.__getitem__.assert_called_once_with("test_db")
    DatabaseService.client = None
# --- END NEW TEST ---

def test_get_collection_not_connected():
    """Tests that getting a collection before connecting raises an exception."""
    DatabaseService.client = None
    with pytest.raises(Exception, match="Database not connected"):
        DatabaseService.get_collection("test_db", "test_coll")

# --- NEW TEST TO COVER 1 MISSING LINE ---
def test_get_collection_success():
    """Tests the success path for get_collection."""
    # Arrange
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_collection = MagicMock()
    
    mock_client.__getitem__.return_value = mock_db
    mock_db.__getitem__.return_value = mock_collection
    DatabaseService.client = mock_client
    
    # Act
    collection = DatabaseService.get_collection("test_db", "test_coll")
    
    # Assert
    assert collection is mock_collection
    mock_client.__getitem__.assert_called_once_with("test_db")
    mock_db.__getitem__.assert_called_once_with("test_coll")
    DatabaseService.client = None
# --- END NEW TEST ---