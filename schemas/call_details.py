from pydantic import BaseModel, Field
from typing import Optional


class InterviewRequest(BaseModel):
    """Schema for interview request."""
    phone_number: str = Field(..., description="Phone number to call")
    candidate_name: str = Field(..., description="Name of the candidate")
    from_number: Optional[str] = Field(default="+13412183420", description="Phone number to call from")

class InterviewResponse(BaseModel):
    """Schema for interview response."""
    status: str
    message: str
    call_sid: Optional[str] = None
    error: Optional[str] = None