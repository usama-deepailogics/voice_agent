from pydantic import BaseModel




class CandidatePayload(BaseModel):
    user_id : str 
    doc_id  :str