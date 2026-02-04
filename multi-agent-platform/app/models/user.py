from pydantic import BaseModel, EmailStr, Field, field_validator
import re
import dns.resolver
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v

    @field_validator('email')
    @classmethod
    def validate_email_dns(cls, v: str) -> str:
        # Pydantic's EmailStr already checks format, but user provided regex, so we can keep it or rely on EmailStr.
        # User explicitly asked for this logic, so I will add it.
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email format")
        
        try:
            domain = v.split('@')[1]
            records = dns.resolver.resolve(domain, 'MX')
            # Check for Null MX record (RFC 7505) which indicates no mail service
            for record in records:
                exchange = str(record.exchange).rstrip('.')
                if not exchange:
                    raise ValueError("Email domain explicitly rejects email (Null MX).")
        except Exception as e:
             # Start of error message allows keeping original "Invalid email format" if needed, 
             # but here we specific to DNS failure or Null MX
             if "explicitly rejects" in str(e):
                 raise e
             raise ValueError("Email domain is not valid or does not accept mail.")
        return v

class UserInDB(UserBase):
    password: str
    created_at: datetime = Field(default_factory=datetime.now)
    is_active: bool = True

class UserResponse(UserBase):
    id: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True
