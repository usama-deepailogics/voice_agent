from pydantic import BaseModel

class PDF_ID(BaseModel):
    """Schema for PDF document identification."""
    ID: str = ""  # Default empty string for ID
    