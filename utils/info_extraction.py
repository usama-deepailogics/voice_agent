from dotenv import load_dotenv
import os 
import logging
from typing import Dict
from openai import OpenAI
from helper.config_file import load_config_file
import yaml 
import logging


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


def extracting_number(text)->Dict:
    try:
        resume_data = {"resume_data": text}
        # print(resume_data)
        prompt  = load_config_file("tools/Resume_Data.yaml")
        system_message = prompt["prompt"]["system_message"]
        user_message =  prompt["prompt"]["user_message"]
        user_message = user_message.format(**resume_data)
        # print("tis/is",user_message)
        logger.info(f"System message: {system_message}")
        logger.info(f"User message: {user_message}")
        
        response = openai_client.chat.completions.create(
            model = "gpt-4.1-mini",
            messages= [
                {"role":"system","content":system_message},
                {"role":"user", "content":user_message}
            ],
            temperature = 0.2,

        )
        return response.choices[0].message.content
    except Exception as e:
        return {"message": str(e)}


