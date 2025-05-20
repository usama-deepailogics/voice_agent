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
from fastapi import FastAPI, HTTPException
import logging.handlers
import traceback
from pydantic import BaseModel
from openai import OpenAI
from utils.info_extraction import extracting_info, end_call_status, storing_data, storing_conversation
from setting import Settings
from schemas.doc_id import CandidatePayload

app = FastAPI()

# Initialize logger
logging.basicConfig(
    level=logging.INFO,  # Use DEBUG level to see detailed logs
    format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",    handlers=[
        logging.StreamHandler()  # Print logs to console
    ],
)
logger = logging.getLogger(__name__)
# Load environment variables
load_dotenv()
logger.info("Environment variables loaded")
AI_client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))


# Initialize Twilio client
account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_HANDLER = os.getenv("TWILIO_URL")
client = Client(account_sid, auth_token)
logger.info("Twilio client initialized")

# Initialize Trieve configuration
TRIEVE_API_KEY = os.environ["TRIEVE_API_KEY"]
TRIEVE_DATASET = os.environ["TRIEVE_API_URL"]
DEEPGRAM_API=os.getenv("DEEPGRAM_API")
logger.info("Trieve API configuration loaded")



## global variable to send conversation back to firebase 
user_id = None
doc_id = None 


async def close_websocket_with_timeout(ws, timeout=5):
    """Close websocket with timeout to avoid hanging if no close frame is received."""
    try:
        await asyncio.wait_for(ws.close(), timeout=timeout)
    except Exception as e:
        logger.error(f"Error during websocket closure: {e}")




async def end_call(params: Dict, twilio_ws=None) -> Dict:
    """End the conversation and close the connection."""
    logger.info(f"params {(params)}")
    candidate_name = params.get("candidate_name", "the candidate")
    position = params.get("position", "the position")
    doc_id  = params.get("doc_id","doc_id")
    user_id  = params.get("user_id","user_id")
    payload = CandidatePayload(user_id=user_id,doc_id=doc_id)
    logger.info(f"Ending call with candidate: {candidate_name} for position: {position}")
    try:
        farewell_message = f"Thank you for your time, {candidate_name}. We appreciate your interest in the {position} position. We'll be in touch soon. Have a great day!"
        end_call_status(payload)
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
            },
            
            "call_status": {
                "status": "Close",
                "message": f"Call completed for id {doc_id}"
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
            subprotocols=["token", DEEPGRAM_API]
        )
        logger.info("Successfully connected to STS service")
        return sts_ws
    except Exception as e:
        logger.error(f"Failed to connect to STS service: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        raise

# Update the PROMPT_TEMPLATE with current date/time and resume data
current_date = datetime.now().strftime("%Y-%m-%d")

PROMPT_TEMPLATE = """You are Alex, a friendly and professional HR virtual assistant conducting initial screening interviews. Your role is to gather candidate information and assess their qualifications.

Current Context:
- Candidate Name: {candidate_name}
- Today's date: {current_date}
- Current time: {current_time}
- Skills: {skills}
- candidate's user_id: {user_id}
- candidate's doc_id: {doc_id}


Personality and Tone:
- Professional but warm and approachable
- Clear and concise in communication
- Focus on key information only

### Conversational flow:
1. Introduction (30 seconds):
   - Brief greeting and introduction
   - Mention you have their resume
   - observe their 2 main technical skills such as development, graphic designing or any other mentioned skills or stack from the resume and ask about experience level of that skill and store that.

2. Key Questions (1-2 minutes):
   - Ask about their notice period
   - Ask about their salary expectations


3. Conclusion (30 seconds):
   - Thank the candidate
   - Use end_call function with both candidate name and position

## Important Guidelines:
- Keep responses brief and focused
- Ask only essential questions
- thank the candidate for having the conversation and then end the call
- Use end_call when all information is gathered

## Remember:
- if there is anything in the resume wrapped for example: "**Candidate Name:** or **skills** then dont say star star candidate name star star or star star skills star star.
- Focus on key information only
- Be direct and efficient"""

# Function definitions that will be sent to the Voice Agent API
FUNCTION_DEFINITIONS = [

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
                },
                "doc_id": {
                    "type": "string",
                    "description": "doc_id given in the prompt",
                },
                "user_id": {
                    "type": "string",
                    "description": "user_id given in the prompt",
                }
            },
            "required": ["candidate_name", "position","doc_id","user_id"],
        },
    },
]

# Map function names to their implementations
FUNCTION_MAP = {
    "end_call": end_call,
}
settings= Settings()
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
        "listen": {"model": "nova-3"},
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
conversation = []
async def twilio_handler(twilio_ws):
    logger.info("Starting Twilio handler")
    audio_queue = asyncio.Queue()
    streamsid_queue = asyncio.Queue()
    global user_id, doc_id  # Access global variables

    async with sts_connect() as sts_ws:
        logger.info("Connected to STS service")

        # send a config message to deepgram
        await sts_ws.send(json.dumps(config_message))
        logger.info("Sent configuration message to STS")

        async def sts_sender(sts_ws):
            logger.info("STS sender started")
            while True:
                chunk = await audio_queue.get() #getting an item from the queue
                await sts_ws.send(chunk)
                logger.debug("Sent audio chunk to STS") #sending to twilio

        async def sts_receiver(sts_ws, twilio_ws):
            logger.info("STS receiver started")
            streamsid = await streamsid_queue.get()
            logger.info(f"Got stream ID: {streamsid}")
            try:
                async for message in sts_ws:
                    if type(message) is str:
                        logger.info(f"Received string message: {message}")
                        decoded = json.loads(message)
                        if decoded["type"] ==  "ConversationText":
                            conversation.append(decoded)
                        if decoded['type'] == 'Welcome':
                            # Send greeting when connection is established
                            greeting_message = {
                                "type": "InjectAgentMessage",
                                "message": "Hello! I am Alex, your HR virtual assistant. I'll be conducting your initial screening interview today. How are you doing?"
                            }
                            await sts_ws.send(json.dumps(greeting_message))
                            logger.info("Sent greeting message")
                        elif decoded['type'] == 'UserStartedSpeaking':
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
                            
                            # Add user_id and doc_id to parameters if not present
                            if 'user_id' not in parameters and user_id:
                                parameters['user_id'] = user_id
                            if 'doc_id' not in parameters and doc_id:
                                parameters['doc_id'] = doc_id
                            
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
                                    # Store conversation before ending call
                                    if user_id and doc_id:
                                        logger.info(f"Storing conversation for user_id: {user_id}, doc_id: {doc_id}")
                                        storing_conversation(data=conversation, user_id=user_id, user_doc_id=doc_id)
                                    
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
                # Store conversation before closing
                if user_id and doc_id:
                    logger.info(f"Storing conversation for user_id: {user_id}, doc_id: {doc_id}")
                    storing_conversation(data=conversation, user_id=user_id, user_doc_id=doc_id)
                await close_websocket_with_timeout(twilio_ws)
                storing_conversation(data=conversation,user_id=user_id,user_doc_id=doc_id)


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
        print(conversation)


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
            <Stream url="wss://8b3e-101-53-238-243.ngrok-free.app/twilio" />
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
async def start_websocket_server():
    server = await websockets.serve(router, "localhost", 5000) #
    logger.info("WebSocket Server starting on ws://localhost:5000")
    await server.wait_closed()


async def initiate_interview_process(candidate_name_payload: CandidatePayload):
    logger.info(f"Initiating interview process for: {candidate_name_payload.user_id}")
    try:
        global user_id, doc_id
        # Use the payload candidate_name
        candidate_info = extracting_info(candidate_name_payload) #
        logger.info(f"Extracted candidate info: {json.dumps(candidate_info, indent=2)}")
        user_id = candidate_name_payload.user_id
        doc_id = candidate_name_payload.doc_id 
        # Ensure PROMPT_TEMPLATE is updated correctly with the new candidate_name
        # This might involve re-formatting it here or ensuring your global update mechanism is safe
        current_date_val = datetime.now().strftime("%Y-%m-%d") #
        current_time_val = datetime.now().strftime("%H:%M:%S") #
        global candidate_name # Or better, pass as arg where needed
        candidate_name=json.dumps(candidate_info.get("name",""))
        
        # Example: Re-format a base prompt template
        formatted_prompt = PROMPT_TEMPLATE.format( # Assuming PROMPT_TEMPLATE is accessible and structured for this
            candidate_name=json.dumps(candidate_info.get("name","")),
            current_date=current_date_val,
            current_time=current_time_val,
            skills=json.dumps(candidate_info.get("skills", [])),
            user_id = json.dumps(user_id),
            doc_id=json.dumps(doc_id)
            )
        # Update config_message's agent instructions if necessary
        config_message["agent"]["think"]["instructions"] = formatted_prompt #
        logger.info(f"updated prompt {formatted_prompt}")

        call = make_outbound_call( #
            from_number="+13412183420", # Consider making these configurable
            to_number=json.dumps(candidate_info.get("phone"))
        )
        logger.info(f"Call SID: {call.sid}")
        return {"status": "success", "message": f"Interview process started for {candidate_name}", "call_sid": call.sid}
    except Exception as e:
        logger.error(f"Error in initiating interview process: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# Modify the main function
@app.post("/start-interview/")
async def start_interview_endpoint(payload: CandidatePayload):
    return await initiate_interview_process(payload)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(start_websocket_server())
    logger.info("FastAPI app started, WebSocket server starting in background.")

