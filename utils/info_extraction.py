from dotenv import load_dotenv
import os 
import logging
from typing import Dict
from openai import OpenAI
# from helper.config_file import load_config_file
import yaml 
import logging
from firebase_admin import credentials, firestore, initialize_app
import firebase_admin
import json


def load_config_file(file:str) -> dict:
    with open(file) as f:
        config_file = yaml.safe_load(f)
    
    return config_file



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

def extracting_info(text)->Dict:
    try:
        db =authenticate_firebase()
        parent_doc_ref = db.collection("pdf_documents").document("UbtouBlziwbttqhGnkbBccex5eU2")
        subcollection_ref = parent_doc_ref.collection("files").document("sXFfYRylkIHVw7uVX1B8")
        subcollection_ref =subcollection_ref.get()
        doc_ref=  subcollection_ref.to_dict()
        resume_data = doc_ref["text"][0]["text"]
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

def end_call_status(doc_id):
    logger.info(f"ending the call status for document id {doc_id}")
    try:
        db = authenticate_firebase()
        parent_doc_ref = db.collection("pdf_documents").document("UbtouBlziwbttqhGnkbBccex5eU2")
        subcollection_ref = parent_doc_ref.collection("files").document("sXFfYRylkIHVw7uVX1B8")
        doc_ref =subcollection_ref.updat({"call_status":"completed","completedAt": firestore.SERVER_TIMESTAMP})
    except Exception as e:
        return {"status": "failed", "message": f"error occured while saving end status in firebase: {e}"}

