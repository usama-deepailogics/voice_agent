import asyncio
import base64
import json
import sys
import websockets
import ssl
from twilio.rest import Client
from dotenv import load_dotenv
import os
from datetime import datetime
from tinydb import TinyDB, Query
from typing import Dict, Optional, List
import requests
import logging
import logging.handlers
import traceback
from openai import OpenAI




def setup_logging():
    """Configure logging with both file and console handlers."""
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Create logger
    logger = logging.getLogger('hr_server')
    logger.setLevel(logging.DEBUG)

    # Create formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )

    # File handler (with rotation)
    file_handler = logging.handlers.RotatingFileHandler(
        'logs/hr_server.log',
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# Initialize logger
logger = setup_logging()

# Load environment variables
load_dotenv()
logger.info("Environment variables loaded")
AI_client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))

# Initialize Twilio client
account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
client = Client(account_sid, auth_token)
logger.info("Twilio client initialized")

# Initialize Trieve configuration
TRIEVE_API_KEY = os.environ["TRIEVE_API_KEY"]
TRIEVE_DATASET = os.environ["TRIEVE_API_URL"]
logger.info("Trieve API configuration loaded")

# Initialize TinyDB
db = TinyDB('hr_database.json')
candidates_table = db.table('candidates')
logger.info("TinyDB initialized")

# Add at the top with other global variables
resume_data = None

async def agent_filler(message_type: Dict) -> Dict:
    """Provide natural conversational filler while processing information."""
    # Handle both string and dict input for message_type
    if isinstance(message_type, dict):
        message_type = message_type.get('message_type', 'processing')
    elif not isinstance(message_type, str):
        message_type = 'processing'
        
    logger.info(f"Using agent filler with message type: {message_type}")
    filler_messages = {
        "lookup": "Let me check that information for you.",
        "processing": "I'm processing that information now.",
        "thinking": "Let me think about that for a moment.",
        "storing": "I'm saving that information now.",
        "verifying": "Let me verify that information."
    }
    return {"message": filler_messages.get(message_type, "One moment please.")}

async def close_websocket_with_timeout(ws, timeout=5):
    """Close websocket with timeout to avoid hanging if no close frame is received."""
    try:
        await asyncio.wait_for(ws.close(), timeout=timeout)
    except Exception as e:
        logger.error(f"Error during websocket closure: {e}")


async def store_skills_experience(params: Dict) -> Dict:
    """Store the candidate's interview responses including skills assessment, availability, and salary expectations."""
    logger.info(f"Storing interview data: {json.dumps(params, indent=2)}")
    try:
        # Use global candidate_name if not provided in params
        global candidate_name
        # Ensure the database file exists
        if not os.path.exists('hr_database.json'):
            with open('hr_database.json', 'w') as f:
                json.dump({}, f)
        
        # Initialize database connection
        db = TinyDB('hr_database.json')
        candidates_table = db.table('candidates')
        
        # Search for existing entry for this candidate
        Candidate = Query()
        existing_entry = candidates_table.get(
            (Candidate.candidate_name == candidate_name) & 
            (Candidate.type == "interview_responses")
        )
        
        if existing_entry:
            # Update existing entry
            doc_id = existing_entry.doc_id
            current_data = existing_entry.copy()
            
            # Update only the fields that are provided in the new params
            if "skills_assessment" in params:
                current_data["skills_assessment"].update(params["skills_assessment"])
            if "availability" in params:
                current_data["availability"].update(params["availability"])
            if "salary_expectations" in params:
                current_data["salary_expectations"].update(params["salary_expectations"])
            
            # Update timestamp
            current_data["timestamp"] = datetime.now().isoformat()
            
            # Update the document
            candidates_table.update(current_data, doc_ids=[doc_id])
            logger.info(f"Updated existing interview data with doc_id: {doc_id}")
        else:
            # Create new entry
            doc_id = candidates_table.insert({
                "candidate_name": candidate_name,
                "skills_assessment": params.get("skills_assessment", {}),
                "availability": params.get("availability", {}),
                "salary_expectations": params.get("salary_expectations", {}),
                "timestamp": datetime.now().isoformat(),
                "type": "interview_responses"
            })
            logger.info(f"Created new interview data with doc_id: {doc_id}")
        
        # Force write to disk
        db.close()
        
        return {
            "status": "success", 
            "message": "Interview responses stored successfully",
            "doc_id": doc_id
        }
    except Exception as e:
        logger.error(f"Error storing interview responses: {str(e)}")
        return {"status": "error", "message": str(e)}

async def end_call(params: Dict, twilio_ws=None) -> Dict:
    """End the conversation and close the connection."""
    candidate_name = params.get("candidate_name", "the candidate")
    position = params.get("position", "the position")
    logger.info(f"Ending call with candidate: {candidate_name} for position: {position}")
    try:
        farewell_message = f"Thank you for your time, {candidate_name}. We appreciate your interest in the {position} position. We'll be in touch soon. Have a great day!"
        return {
            "status": "success",
            "message": farewell_message,
            "action": "end_call",
            "inject_message": {
                "type": "inject",
                "content": farewell_message
            },
            "function_response": {
                "status": "success",
                "message": "Call ended successfully"
            },
            "close_message": {
                "type": "close",
                "message": "Call completed"
            }
        }
    except Exception as e:
        logger.error(f"Error ending call: {str(e)}")
        return {"status": "error", "message": str(e)}

def sts_connect():
    """Connect to the Speech-to-Speech service."""
    logger.info("Attempting to connect to STS service")
    try:
        sts_ws = websockets.connect(
            "wss://agent.deepgram.com/agent",
            subprotocols=["token", "a82226c0eb2d60a51b54117a166297a32b5ce991"]
        )
        logger.info("Successfully connected to STS service")
        return sts_ws
    except Exception as e:
        logger.error(f"Failed to connect to STS service: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        raise

# Update the PROMPT_TEMPLATE with current date/time and resume data
current_date = datetime.now().strftime("%Y-%m-%d")
current_time = datetime.now().strftime("%H:%M:%S")
candidate_name = "Catrina Janssen"

PROMPT_TEMPLATE = """You are Alex, a friendly and professional HR virtual assistant conducting initial screening interviews. Your role is to gather candidate information and assess their qualifications.

Current Context:
- Candidate Name: {candidate_name}
- Today's date: {current_date}
- Current time: {current_time}
- Skills: {skills}
- Technologies: {technologies}

Personality and Tone:
- Professional but warm and approachable
- Clear and concise in communication
- Focus on key information only

Interview Flow:
1. Introduction (30 seconds):
   - Brief greeting and introduction
   - Mention you have their resume
   - observe their 2 main skills from the resume and ask about experience level

2. Key Questions (1-2 minutes):
   - Ask about their notice period
   - Ask about their salary expectations
   - Ask one follow-up question about their strongest skill

3. Conclusion (30 seconds):
   - Thank the candidate
   - Use end_call function with both candidate name and position

Important Guidelines:
- Keep responses brief and focused
- Ask only essential questions
- Use store_skills_experience after each response
- End the call after getting all required information

Function Usage:
- Use store_skills_experience to save:
  * Skills assessment
  * Notice period
  * Salary expectations
- Use end_call when all information is gathered

Remember:
- if there is anything in the resume wrapped for example: "**Candidate Name:** or **skills** then dont say star star candidate name star star or star star skills star star.
- Keep the conversation under 3 minutes
- Focus on key information only
- Be direct and efficient"""

# Function definitions that will be sent to the Voice Agent API
FUNCTION_DEFINITIONS = [
    {
        "name": "agent_filler",
        "description": """Use this function to provide natural conversational filler while processing information.
        ALWAYS call this function first with message_type='lookup' when you're about to check candidate information.
        After calling this function, you MUST immediately follow up with the appropriate lookup function.""",
        "parameters": {
            "type": "object",
            "properties": {
                "message_type": {
                    "type": "string",
                    "description": "Type of filler message to use. Use 'lookup' when about to search for information.",
                    "enum": ["lookup", "processing", "thinking", "storing", "verifying"],
                }
            },
            "required": ["message_type"],
        },
    },
    {
        "name": "store_skills_experience",
        "description": """Store the candidate's interview responses. Use this function when:
        - You've asked about their skills and experience
        - You've asked about their availability and notice period
        - You've asked about their salary expectations
        - You've received responses from the candidate
        
        Always verify the response is clear before storing.""",
        "parameters": {
            "type": "object",
            "properties": {
                "skills_assessment": {
                    "type": "object",
                    "description": "Assessment of candidate's skills and experience",
                    "properties": {
                        "main_skills": {
                            "type": "array",
                            "description": "List of main skills identified from resume",
                            "items": {"type": "string"}
                        },
                        "skill_responses": {
                            "type": "array",
                            "description": "List of candidate's responses about their skills",
                            "items": {"type": "string"}
                        }
                    }
                },
                "availability": {
                    "type": "object",
                    "description": "Candidate's availability information",
                    "properties": {
                        "immediate_availability": {
                            "type": "boolean",
                            "description": "Whether the candidate can join immediately"
                        },
                        "notice_period": {
                            "type": "string",
                            "description": "Candidate's notice period if not immediately available"
                        }
                    }
                },
                "salary_expectations": {
                    "type": "object",
                    "description": "Candidate's salary expectations",
                    "properties": {
                        "expected_salary": {
                            "type": "string",
                            "description": "Candidate's expected salary range"
                        },
                        "negotiable": {
                            "type": "boolean",
                            "description": "Whether the salary is negotiable"
                        }
                    }
                }
            },
            "required": ["skills_assessment", "availability", "salary_expectations"],
        },
    },
    {
        "name": "end_call",
        "description": """End the conversation and close the connection. Call this function when:
        - The resume-based interview is complete
        - The candidate indicates they're done
        - You need to conclude the conversation
        
        Examples of triggers:
        - "Thank you for your time"
        - "That concludes our interview"
        - "We'll be in touch soon"
        - "Have a great day"
        
        Do not call this function if the conversation is still ongoing.""",
        "parameters": {
            "type": "object",
            "properties": {
                "candidate_name": {
                    "type": "string",
                    "description": "Name of the candidate for the farewell message.",
                },
                "position": {
                    "type": "string",
                    "description": "Position the candidate applied for.",
                }
            },
            "required": ["candidate_name", "position"],
        },
    },
]

# Map function names to their implementations
FUNCTION_MAP = {
    "agent_filler": agent_filler,
    "store_skills_experience": store_skills_experience,
    "end_call": end_call,
}

async def twilio_handler(twilio_ws):
    logger.info("Starting Twilio handler")
    audio_queue = asyncio.Queue()
    streamsid_queue = asyncio.Queue()

    async with sts_connect() as sts_ws:
        logger.info("Connected to STS service")
        config_message = {
            "type": "SettingsConfiguration",
            "audio": {
                "input": {
                    "encoding": "mulaw",
                    "sample_rate": 8000,
                },
                "output": {
                    "encoding": "mulaw",
                    "sample_rate": 8000,
                    "container": "none",
                },
            },
            "agent": {
                "listen": {"model": "nova-2"},
                "think": {
                    "provider": {
                        "type": "open_ai",
                    },
                    "model": "gpt-4o-mini",
                    "instructions": PROMPT_TEMPLATE,
                    "functions": FUNCTION_DEFINITIONS,
                },
                "speak": {"model": "aura-asteria-en"},
            },
        }

        await sts_ws.send(json.dumps(config_message))
        logger.info("Sent configuration message to STS")

        async def sts_sender(sts_ws):
            logger.info("STS sender started")
            while True:
                chunk = await audio_queue.get()
                await sts_ws.send(chunk)
                logger.debug("Sent audio chunk to STS")

        async def sts_receiver(sts_ws, twilio_ws):
            logger.info("STS receiver started")
            streamsid = await streamsid_queue.get()
            logger.info(f"Got stream ID: {streamsid}")
            try:
                async for message in sts_ws:
                    if type(message) is str:
                        logger.info(f"Received string message: {message}")
                        decoded = json.loads(message)
                        if decoded['type'] == 'UserStartedSpeaking':
                            logger.info("User started speaking")
                            clear_message = {
                                "event": "clear",
                                "streamSid": streamsid
                            }
                            await twilio_ws.send(json.dumps(clear_message))
                        elif decoded['type'] == 'FunctionCallRequest':
                            function_name = decoded.get('function_name')
                            function_call_id = decoded.get('function_call_id')
                            parameters = decoded.get('input', {})
                            
                            logger.info(f"Function call received: {function_name}")
                            logger.info(f"Parameters: {parameters}")
                            
                            try:
                                func = FUNCTION_MAP.get(function_name)
                                if not func:
                                    raise ValueError(f"Function {function_name} not found")
                                
                                if function_name == "end_call":
                                    result = await func(parameters, twilio_ws)
                                else:
                                    result = await func(parameters)
                                
                                if function_name == "end_call":
                                    # Extract messages
                                    inject_message = result["inject_message"]
                                    function_response = result["function_response"]
                                    close_message = result["close_message"]

                                    # First send the function response
                                    response = {
                                        "type": "FunctionCallResponse",
                                        "function_call_id": function_call_id,
                                        "output": json.dumps(function_response),
                                    }
                                    await sts_ws.send(json.dumps(response))
                                    logger.info(f"Function response sent: {json.dumps(function_response)}")

                                    # Then wait for farewell sequence to complete
                                    await wait_for_farewell_completion(sts_ws, twilio_ws, inject_message)

                                    # Finally send the close message and exit
                                    logger.info("Sending ws close message")
                                    await close_websocket_with_timeout(twilio_ws)
                                    return
                                
                                response = {
                                    "type": "FunctionCallResponse",
                                    "function_call_id": function_call_id,
                                    "output": json.dumps(result)
                                }
                                await sts_ws.send(json.dumps(response))
                                logger.info(f"Function response sent: {json.dumps(result)}")
                                
                            except Exception as e:
                                logger.error(f"Error executing function: {str(e)}")
                                result = {"error": str(e)}
                                response = {
                                    "type": "FunctionCallResponse",
                                    "function_call_id": function_call_id,
                                    "output": json.dumps(result)
                                }
                                await sts_ws.send(json.dumps(response))
                        continue

                    logger.debug(f"Received message type: {type(message)}")
                    raw_mulaw = message
                    media_message = {
                        "event": "media",
                        "streamSid": streamsid,
                        "media": {"payload": base64.b64encode(raw_mulaw).decode("ascii")},
                    }
                    await twilio_ws.send(json.dumps(media_message))
                    logger.debug("Sent media message to Twilio")
            except Exception as e:
                logger.error(f"Error in STS receiver: {str(e)}")
                logger.debug(f"Full traceback: {traceback.format_exc()}")
            finally:
                await close_websocket_with_timeout(twilio_ws)

        async def twilio_receiver(twilio_ws):
            logger.info("Twilio receiver started")
            BUFFER_SIZE = 20 * 160
            inbuffer = bytearray(b"")
            try:
                async for message in twilio_ws:
                    try:
                        data = json.loads(message)
                        if data["event"] == "start":
                            logger.info("Got stream ID from Twilio")
                            start = data["start"]
                            streamsid = start["streamSid"]
                            await streamsid_queue.put(streamsid)
                        elif data["event"] == "connected":
                            logger.info("Twilio connection established")
                            continue
                        elif data["event"] == "media":
                            media = data["media"]
                            chunk = base64.b64decode(media["payload"])
                            if media["track"] == "inbound":
                                inbuffer.extend(chunk)
                                logger.debug("Added chunk to buffer")
                        elif data["event"] == "stop":
                            logger.info("Received stop event from Twilio")
                            break

                        while len(inbuffer) >= BUFFER_SIZE:
                            chunk = inbuffer[:BUFFER_SIZE]
                            await audio_queue.put(chunk)
                            inbuffer = inbuffer[BUFFER_SIZE:]
                            logger.debug("Processed buffer chunk")
                    except json.JSONDecodeError as e:
                        logger.error(f"Error decoding JSON: {str(e)}")
                        continue
                    except Exception as e:
                        logger.error(f"Error in Twilio receiver: {str(e)}")
                        logger.debug(f"Full traceback: {traceback.format_exc()}")
                        break
            except websockets.exceptions.ConnectionClosed:
                logger.info("Twilio WebSocket connection closed")
            except Exception as e:
                logger.error(f"Error in Twilio receiver: {str(e)}")
                logger.debug(f"Full traceback: {traceback.format_exc()}")
            finally:
                # Process any remaining audio data
                if len(inbuffer) > 0:
                    try:
                        await audio_queue.put(inbuffer)
                        logger.debug("Processed remaining buffer")
                    except Exception as e:
                        logger.error(f"Error processing remaining buffer: {str(e)}")

        logger.info("Starting async tasks")
        await asyncio.wait(
            [
                asyncio.ensure_future(sts_sender(sts_ws)),
                asyncio.ensure_future(sts_receiver(sts_ws, twilio_ws)),
                asyncio.ensure_future(twilio_receiver(twilio_ws)),
            ]
        )

        logger.info("Closing Twilio WebSocket connection")
        await twilio_ws.close()

async def wait_for_farewell_completion(sts_ws, twilio_ws, inject_message):
    """Wait for the farewell message to be fully processed."""
    try:
        # Send the farewell message
        await sts_ws.send(json.dumps(inject_message))
        # Wait a moment for the message to be processed
        await asyncio.sleep(2)
    except Exception as e:
        logger.error(f"Error during farewell completion: {str(e)}")

async def router(websocket, path):
    logger.info(f"Incoming connection on path: {path}")
    if path == "/twilio":
        logger.info("Starting Twilio handler")
        await twilio_handler(websocket)



def make_outbound_call(to_number, from_number):
    logger.info(f"Making outbound call to {to_number} from {from_number}")
    twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="en">"This call may be monitored or recorded."</Say>
    <Connect>
        <Stream url="wss://d024-101-53-238-243.ngrok-free.app/twilio" />
    </Connect>
</Response>'''
    
    try:
        call = client.calls.create(
            twiml=twiml,
            to=to_number,
            from_=from_number
        )
        logger.info(f"Call created successfully with SID: {call.sid}")
        return call
    except Exception as e:
        logger.error(f"Error creating call: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        raise

# Add the extract_candidate_info function
def extract_candidate_info(candidate_name):
    """Extract structured information about the candidate from Trieve."""
    logger.info(f"Checking Trieve database for candidate: {candidate_name}")
    url = "https://api.trieve.ai/api/chunk/search"
    payload = {
        "query": candidate_name,
        "search_type": "semantic",
    }
    headers = {
        "Authorization": TRIEVE_API_KEY,
        "TR-Dataset": TRIEVE_DATASET,
        "X-API-Version": "V1",
        "Content-Type": "application/json"
    }
    response = requests.request("POST", url, json=payload, headers=headers)
    raw_resume_data = response.text
    
    # Process the raw resume data
    prompt = f"""
    Extract skills, technologies, project names, and durations from this transcript only about the {candidate_name}:
    "{raw_resume_data}"
    
    Respond in JSON:
    {{
        "skills": [],
        "projects": [],
        "technologies": [],
        "duration": ""
    }}
    """

    response = AI_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
    )
    choices = response.choices[0].message.content
    return json.loads(choices)

# Modify the main function
def main():
    logger.info("Starting HR Server application")
    try:
        # Declare global variables at the start of the function
        global PROMPT_TEMPLATE
        
        # Extract candidate info before making the call
        candidate_info = extract_candidate_info(candidate_name)
        logger.info(f"Extracted candidate info: {json.dumps(candidate_info, indent=2)}")
        
        # Format the prompt template with all available information
        formatted_prompt = PROMPT_TEMPLATE.format(
            candidate_name=candidate_name,
            current_date=current_date,
            current_time=current_time,
            skills=json.dumps(candidate_info.get("skills", [])),
            technologies=json.dumps(candidate_info.get("technologies", [])),
        )
        print(formatted_prompt)
        
        # Update the global PROMPT_TEMPLATE
        PROMPT_TEMPLATE = formatted_prompt
        
        # Make an outbound call
        call = make_outbound_call(
            from_number="+13412183420",
            to_number="+923136125986"
        )
        logger.info(f"Call SID: {call.sid}")

        # Start the WebSocket server
        server = websockets.serve(router, "localhost", 5000)
        logger.info("Server starting on ws://localhost:5000")

        asyncio.get_event_loop().run_until_complete(server)
        asyncio.get_event_loop().run_forever()
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main() or 0)