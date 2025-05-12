from google.cloud import storage as gcs_storage
from dotenv import load_dotenv
import os 
import trieve_py_client
from trieve_py_client.models.upload_file_req_payload import UploadFileReqPayload
from trieve_py_client.models.upload_file_response_body import UploadFileResponseBody
from trieve_py_client.rest import ApiException
from pprint import pprint
import logging
from typing import Dict, List, Optional
import io
import base64
import requests
from pydantic import BaseModel, Field
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# Initialize FastAPI app
app = FastAPI(
    title="PDF Processing API",
    description="API for processing PDF files from Google Cloud Storage and uploading to Trieve",
    version="1.0.0"
)

class PDF_ID(BaseModel):
    """Schema for PDF document identification."""
    ID: str = Field(default="", description="Path to the PDF file or folder in GCS")

class ProcessRequest(BaseModel):
    """Schema for processing request."""
    phone_number: str = Field(..., description="Phone number to call")
    candidate_name: str = Field(..., description="Name of the candidate")
    folder_path: str = Field(..., description="Path to the folder containing PDFs in GCS")

class ProcessResponse(BaseModel):
    """Schema for processing response."""
    status: str = Field(..., description="Status of the processing")
    message: str = Field(..., description="Message describing the result")
    processed_files: Optional[List[Dict]] = Field(default=None, description="List of processed files")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
    handlers=[
        logging.StreamHandler()
    ],
)

logger = logging.getLogger(__name__)
load_dotenv()

# Get configuration from environment variables
config_file = os.getenv("CONFIG_FILE", "fir-47b23-firebase-adminsdk-j70zf-cfe3ad14b1.json")
bucket_name = os.getenv("BUCKET", "fir-47b23.appspot.com")
trieve_api_key = os.getenv("TRIEVE_API_KEY")
trieve_dataset = os.getenv("TRIEVE_API_URL")

def verify_bucket_access():
    """Verify that we can access the bucket."""
    try:
        gcs_client = gcs_storage.Client.from_service_account_json(config_file)
        bucket = gcs_client.bucket(bucket_name)
        
        if not bucket.exists():
            logger.error(f"Bucket {bucket_name} does not exist")
            return False
            
        next(iter(bucket.list_blobs(max_results=1)), None)
        logger.info(f"Successfully verified access to bucket: {bucket_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to verify bucket access: {str(e)}")
        return False

def bucket_docs(query: PDF_ID):
    """Process documents in the specified folder."""
    try:
        if not query.ID:
            return {"status": "error", "message": "No folder path provided"}

        if not verify_bucket_access():
            return {"status": "error", "message": f"Cannot access bucket: {bucket_name}"}

        prefix = query.ID.lstrip('/').replace('\\', '/')
        logger.info(f"Searching for files with prefix: {prefix}")
        
        try:
            gcs_client = gcs_storage.Client.from_service_account_json(config_file)
            bucket = gcs_client.bucket(bucket_name)
        except Exception as e:
            logger.error(f"Failed to initialize GCS client: {str(e)}")
            return {"status": "error", "message": f"GCS initialization failed: {str(e)}"}

        try:
            blobs = bucket.list_blobs(prefix=prefix)
            result = []
            
            blob_list = list(blobs)
            if not blob_list:
                logger.warning(f"No files found in path: {prefix}")
                return {"status": "warning", "message": f"No files found in path: {prefix}"}

            for blob in blob_list:
                if blob.name.endswith('/'):
                    continue
                    
                logger.info(f"Processing file: {blob.name}")
                sub_query = PDF_ID(ID=blob.name)
                
                try:
                    moderation = pdf_extraction(sub_query)
                    result_obj = {"image": blob.name, **moderation}
                    result.append(result_obj)
                except Exception as e:
                    logger.error(f"Error processing {blob.name}: {str(e)}")
                    result_obj = {"image": blob.name, "status": "error", "message": str(e)}
                    result.append(result_obj)
            
            return result

        except Exception as e:
            logger.error(f"Error listing blobs: {str(e)}")
            return {"status": "error", "message": f"Failed to list files: {str(e)}"}

    except Exception as e:
        logger.error(f"Batch moderation failed: {str(e)}")
        return {"status": "error", "message": str(e)}

def pdf_extraction(pdf_id) -> Dict:
    """Process individual PDF file and upload to Trieve."""
    try:
        gcs_client = gcs_storage.Client.from_service_account_json(config_file)
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(pdf_id.ID)

        if not blob.exists():
            logger.error(f"File not found: {pdf_id.ID}")
            return {"status": "error", "message": f"File not found: {pdf_id.ID}"}

        image_bytes = io.BytesIO()
        blob.download_to_file(image_bytes)
        image_bytes.seek(0)
        logger.info(f"Doc {pdf_id.ID} is being processed")

        try:
            encoded_string = base64.b64encode(image_bytes.getvalue())
            decoded_str = encoded_string.decode('utf-8')
        except Exception as e:
            logger.error(f"Error encoding file: {str(e)}")
            return {"status": "error", "message": f"File encoding failed: {str(e)}"}

        configuration = trieve_py_client.Configuration(
            host="https://api.trieve.ai"
        )
        configuration.api_key['ApiKey'] = trieve_api_key
        configuration.api_key_prefix['ApiKey'] = 'Bearer'

        try:
            with trieve_py_client.ApiClient(configuration) as api_client:
                api_instance = trieve_py_client.FileApi(api_client)
                
                upload_file_req_payload = trieve_py_client.UploadFileReqPayload(
                    base64_file=decoded_str,
                    file_name=f"{pdf_id.ID}.pdf",
                    link="https://example.com",
                    tag_set=["resume", "pdf"],
                    time_stamp=datetime.now().isoformat(),
                    target_splits_per_chunk=1,
                    metadata={
                        "source": "gcs",
                        "bucket": bucket_name
                    },
                    pdf2md_options={
                        "use_pdf2md_ocr": True
                    }
                )

                api_response = api_instance.upload_file_handler(trieve_dataset, upload_file_req_payload)
                logger.info(f"Successfully uploaded file to Trieve: {pdf_id.ID}")
                return {"status": "success", "message": "File processed successfully"}

        except Exception as e:
            logger.error(f"Trieve upload failed: {str(e)}")
            return {"status": "error", "message": f"Trieve upload failed: {str(e)}"}

    except Exception as e:
        logger.error(f"PDF extraction failed: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.post("/process-pdfs", response_model=ProcessResponse)
async def process_pdfs(request: ProcessRequest):
    """
    Process PDF files for a given candidate.
    
    Args:
        request: ProcessRequest containing phone number, candidate name, and folder path
        
    Returns:
        ProcessResponse with processing status and results
    """
    try:
        # Validate inputs
        if not request.phone_number or not request.candidate_name or not request.folder_path:
            raise HTTPException(status_code=400, detail="Missing required fields")

        # Process the PDFs
        query = PDF_ID(ID=request.folder_path)
        result = bucket_docs(query)

        # Prepare response
        if isinstance(result, list):
            return ProcessResponse(
                status="success",
                message=f"Processed {len(result)} files for candidate {request.candidate_name}",
                processed_files=result
            )
        else:
            return ProcessResponse(
                status=result.get("status", "error"),
                message=result.get("message", "Unknown error occurred"),
                processed_files=None
            )

    except Exception as e:
        logger.error(f"API error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        if verify_bucket_access():
            return {"status": "healthy", "message": "Service is running and can access GCS"}
        else:
            return {"status": "unhealthy", "message": "Cannot access GCS bucket"}
    except Exception as e:
        return {"status": "unhealthy", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)  
