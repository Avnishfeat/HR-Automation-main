from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from bson import ObjectId

# Helper to handle MongoDB ObjectId
class PyObjectId(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

# Base properties shared by all models
class UserBase(BaseModel):
    email: EmailStr = Field(..., description="Unique email address")
    full_name: str = Field(..., min_length=1, description="User's full name")
    organization_name: str = Field(..., min_length=1, description="Company or Organization")

    @field_validator('email')
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()

# Schema for creating a user (What the client sends)
class UserCreate(UserBase): 
    email: EmailStr
    password: str = Field(..., min_length=6)

# Schema for reading a user from DB (Includes the hashed password)
class UserInDB(UserBase):
    hashed_password: str
    disabled: bool = False

# Schema for returning user data (Hides the password)
class UserResponse(UserBase):
    pass
   
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator('email')
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()