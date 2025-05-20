from dotenv import load_dotenv
import os 
import logging
from typing import Dict
from openai import OpenAI
from helper.config_file import load_config_file
import yaml 
import logging
from firebase_admin import credentials, firestore, initialize_app
import firebase_admin
import json
from schemas.doc_id import CandidatePayload





logging.basicConfig(
    level=logging.INFO,  # Use DEBUG level to see detailed logs
    format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",    handlers=[
        logging.StreamHandler()  # Print logs to console
    ],
)

logger = logging.getLogger(__name__)
load_dotenv()
api_key = os.getenv("OPENAI_KEY")
openai_client = OpenAI(api_key=api_key)
FIREBASE_CONFIG= os.getenv("CONFIG_FILE")

def authenticate_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_CONFIG)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    return db

def extracting_info(text:CandidatePayload)->Dict:
    try:
        user_id = text.user_id
        doc_id = text.doc_id
        db =authenticate_firebase()
        parent_doc_ref = db.collection("resumes").document(user_id)
        subcollection_ref = parent_doc_ref.collection("files").document(doc_id)
        subcollection_ref =subcollection_ref.get()
        doc_ref=  subcollection_ref.to_dict()
        resume_data = doc_ref["resume_data"]
        logger.info(f"extracted CV : {resume_data}")
        resume_data = {"resume_data": resume_data}
        prompt  = load_config_file("tools/Resume_Data.yaml")
        system_message = prompt["prompt"]["system_message"]
        user_message =  prompt["prompt"]["user_message"]
        user_message = user_message.format(**resume_data)
        # print("tis/is",user_message)
        logger.info(f"System message: {system_message}")
        logger.info(f"User message: {user_message}")
        
        response = openai_client.chat.completions.create(
            model = "gpt-4o-mini",
            messages= [
                {"role":"system","content":system_message},
                {"role":"user", "content":user_message}
            ],
            temperature = 0.2,

        )
        logger.info(f"raw response {response.choices[0].message.content}")
        logger.info(f"raw response {json.loads(response.choices[0].message.content)}")
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"message": str(e)}

def end_call_status(text:CandidatePayload):
    logger.info(f"ending the call status for document id {text.user_id}")
    try:
        user_id = text.user_id
        doc_id = text.doc_id
        logger.info(f"ending call status for uid {user_id} and {doc_id}")
        db = authenticate_firebase()
        parent_doc_ref = db.collection("resumes").document(user_id)
        subcollection_ref = parent_doc_ref.collection("files").document(doc_id)
        doc_ref =subcollection_ref.set({"call_status":"completed","completedAt": firestore.SERVER_TIMESTAMP},merge=True)
    except Exception as e:
        return {"status": "failed", "message": f"error occured while saving end status in firebase: {e}"}
    

def storing_data(data, user_id, user_doc_id):
    logger.info(f"ending the call status for document id {user_id}")
    try:
        payload = {"call_status":"completed","completedAt": firestore.SERVER_TIMESTAMP,"candidate_response":data}
        doc_id = user_doc_id
        db = authenticate_firebase()
        db.collection("responses").document(user_id).collection("response").document(doc_id).set(payload,merge=True)
        logger.info(f"data has been added for user {user_id}")
    except Exception as e:
        return {"status": "failed", "message": f"error occured while saving end status in firebase: {e}"}

def storing_conversation(data, user_id, user_doc_id):
    logger.info(f"storing conversation for user id {user_id}")
    try:
        payload = {"call_status":"completed","completedAt": firestore.SERVER_TIMESTAMP,"conversation":data}
        doc_id = user_doc_id
        db = authenticate_firebase()
        db.collection("responses").document(user_id).collection("conversation").document(doc_id).set(payload,merge=True)
        logger.info(f"conversation has been added for user {user_id}")
    except Exception as e:
        return {"status": "failed", "message": f"error occured while saving end status in firebase: {e}"}

