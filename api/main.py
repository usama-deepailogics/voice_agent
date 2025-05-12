from fastapi import FastAPI, HTTPException
import asyncio
import logging
from datetime import datetime
import os
from server import make_outbound_call, extract_candidate_info, PROMPT_TEMPLATE
from schemas.call_details import InterviewRequest, InterviewResponse
from schemas.Resume import Resume_Data
from dotenv import load_dotenv
from utils.info_extraction import extracting_number
# Initialize FastAPI app
app = FastAPI()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


@app.post("/start-interview", response_model=InterviewResponse)
async def start_interview(request: Resume_Data):
    """
    Start an automated interview with a candidate.
    
    Args:
        request: InterviewRequest containing phone number and candidate name
        
    Returns:
        InterviewResponse with call status and details
    """
    try:
        # Validate inputs
        if not request.resume_data:
            raise HTTPException(status_code=400, detail="Resume is not found")

        # Extract candidate info
        

        # Format the prompt template
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now().strftime("%H:%M:%S")
        resume = request.resume_data

        candidate_skills = resume["skills"]
        candidate_name = resume["name"]
        candidate_email = resume["email"]
        candidate_number = resume["phone"]

        logger.info(f"Data is fetched for the candidate {candidate_name}, {candidate_name} has following skills \n {candidate_skills}, \
                    \n candidate_email {candidate_email}")
        
        formatted_prompt = PROMPT_TEMPLATE.format(
            candidate_name=candidate_name,
            current_date=current_date,
            current_time=current_time,
            skills= candidate_skills
        )

        # Make the outbound call

        call = make_outbound_call(
            to_number=candidate_number,
            from_number="+13412183420"
        )

        return InterviewResponse(
            status="success",
            message="Interview call initiated successfully",
            call_sid=call.sid
        )

    except Exception as e:
        logger.error(f"Error starting interview: {str(e)}")
        return InterviewResponse(
            status="error",
            message="Failed to start interview",
            error=str(e)
        )

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "message": "Service is running"}
