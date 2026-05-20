# app/infrastructure/__init__.py
"""
Infrastructure layer containing low-level system integrations.
"""

from .browser import MeetController, MeetSessionManager

__all__ = [
    'MeetController',
    'MeetSessionManager'
]