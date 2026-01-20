# app/config/secrets.py
"""
Centralized Secrets Management

Provides a single source of truth for all sensitive configuration.
Features:
- Unified access to secrets regardless of backend
- Built-in masking for safe logging
- Validation on access
- Support for environment variables (dev) and cloud secret managers (prod)
"""

import os
import logging
import re
from typing import Optional, Dict, Any, List
from functools import lru_cache
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SecretBackend(Enum):
    """Available secret storage backends."""
    ENVIRONMENT = "environment"
    # Future: GOOGLE_SECRET_MANAGER = "google_secret_manager"
    # Future: AWS_SECRETS_MANAGER = "aws_secrets_manager"


@dataclass
class SecretDefinition:
    """Defines a secret with its metadata."""
    name: str
    required: bool = True
    description: str = ""
    pattern: Optional[str] = None  # Regex pattern for validation
    

class SecretValue:
    """
    Wrapper for secret values that prevents accidental logging.
    The actual value is hidden in __repr__ and __str__.
    """
    
    def __init__(self, value: Optional[str], name: str = "SECRET"):
        self._value = value
        self._name = name
    
    @property
    def value(self) -> Optional[str]:
        """Get the actual secret value."""
        return self._value
    
    def __str__(self) -> str:
        """Masked representation for logging safety."""
        if self._value is None:
            return f"<{self._name}: NOT SET>"
        return f"<{self._name}: ****{self._value[-4:] if len(self._value) > 4 else '****'}>"
    
    def __repr__(self) -> str:
        return self.__str__()
    
    def __bool__(self) -> bool:
        """Allow truthy checks without exposing value."""
        return self._value is not None and len(self._value) > 0
    
    def __eq__(self, other) -> bool:
        if isinstance(other, SecretValue):
            return self._value == other._value
        return self._value == other


class SecretsManager:
    """
    Centralized secrets manager with validation and masking.
    
    Usage:
        from app.config.secrets import secrets
        
        api_key = secrets.get("GEMINI_API_KEY")  # Returns actual string value
        masked = secrets.get_masked("GEMINI_API_KEY")  # Returns SecretValue for safe logging
    """
    
    # Registry of all known secrets
    SECRET_DEFINITIONS: List[SecretDefinition] = [
        SecretDefinition(
            name="GEMINI_API_KEY",
            required=True,
            description="Google Gemini API key for AI models",
            pattern=r"^AIza[A-Za-z0-9_-]{20,}$"  # Gemini API key: starts with AIza, 20+ additional chars
        ),
        SecretDefinition(
            name="MONGODB_URL",
            required=True,
            description="MongoDB connection string",
            pattern=r"^mongodb(\+srv)?://"
        ),
        SecretDefinition(
            name="GOOGLE_APPLICATION_CREDENTIALS",
            required=False,
            description="Path to Google Cloud service account JSON"
        ),
        SecretDefinition(
            name="GOOGLE_CLOUD_PROJECT",
            required=False,
            description="Google Cloud project ID for STT/TTS"
        ),
    ]
    
    def __init__(self, backend: SecretBackend = SecretBackend.ENVIRONMENT):
        self._backend = backend
        self._cache: Dict[str, Optional[str]] = {}
        self._validated = False
        
    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a secret value by name.
        
        Args:
            name: The secret name (e.g., "GEMINI_API_KEY")
            default: Default value if not found
            
        Returns:
            The actual secret value as a string, or default if not found
        """
        if name not in self._cache:
            self._cache[name] = self._load_secret(name)
        
        value = self._cache[name]
        return value if value is not None else default
    
    def get_masked(self, name: str) -> SecretValue:
        """
        Get a secret wrapped in SecretValue for safe logging.
        
        Args:
            name: The secret name
            
        Returns:
            SecretValue wrapper that hides the actual value in logs
        """
        return SecretValue(self.get(name), name)
    
    def get_required(self, name: str) -> str:
        """
        Get a secret that must exist, raising an error if missing.
        
        Args:
            name: The secret name
            
        Returns:
            The secret value
            
        Raises:
            ValueError: If the secret is not set
        """
        value = self.get(name)
        if value is None:
            raise ValueError(f"Required secret '{name}' is not set")
        return value
    
    def _load_secret(self, name: str) -> Optional[str]:
        """Load a secret from the configured backend."""
        if self._backend == SecretBackend.ENVIRONMENT:
            return os.getenv(name)
        # Future: Add other backends here
        return None
    
    def validate_all(self) -> tuple[bool, List[str]]:
        """
        Validate all defined secrets.
        
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        
        for secret_def in self.SECRET_DEFINITIONS:
            value = self.get(secret_def.name)
            
            # Check required
            if secret_def.required and not value:
                errors.append(f"Required secret '{secret_def.name}' is not set")
                continue
            
            # Check pattern if value exists
            if value and secret_def.pattern:
                if not re.match(secret_def.pattern, value):
                    errors.append(
                        f"Secret '{secret_def.name}' does not match expected pattern"
                    )
        
        self._validated = len(errors) == 0
        return self._validated, errors
    
    def get_secret_names(self) -> List[str]:
        """Get list of all secret names for log sanitization."""
        return [s.name for s in self.SECRET_DEFINITIONS]
    
    def get_all_values_for_masking(self) -> List[str]:
        """
        Get all secret values for log masking.
        Only call this for log filter setup, not for general use.
        """
        values = []
        for secret_def in self.SECRET_DEFINITIONS:
            value = self.get(secret_def.name)
            if value:
                values.append(value)
        return values
    
    def clear_cache(self):
        """Clear the secret cache, forcing reload on next access."""
        self._cache.clear()
        self._validated = False
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check the health of secrets configuration.
        
        Returns:
            Dictionary with health status for each secret
        """
        status = {}
        for secret_def in self.SECRET_DEFINITIONS:
            value = self.get(secret_def.name)
            status[secret_def.name] = {
                "set": value is not None,
                "required": secret_def.required,
                "valid": True  # Detailed validation could be added
            }
            
            # Validate pattern if exists
            if value and secret_def.pattern:
                status[secret_def.name]["valid"] = bool(
                    re.match(secret_def.pattern, value)
                )
        
        return status


# Global singleton instance
@lru_cache(maxsize=1)
def get_secrets_manager() -> SecretsManager:
    """Get the global secrets manager instance."""
    return SecretsManager()


# Convenience accessor
secrets = get_secrets_manager()
