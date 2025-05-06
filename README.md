# HR Virtual Assistant

An AI-powered HR virtual assistant that conducts initial screening interviews with job candidates using Twilio for voice calls and Trieve for resume data management.

## Features

- Automated candidate screening calls
- Integration with Trieve.ai for resume data
- Local database storage using TinyDB
- Natural conversation flow
- Professional HR interview process

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file with the following variables:
```
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TRIEVE_API_KEY=your_trieve_api_key
```

3. Set up ngrok for WebSocket connection:
```bash
ngrok http 5000
```

4. Update the WebSocket URL in `hr_assistant.py` with your ngrok URL.

## Usage

1. Start the server:
```bash
python hr_assistant.py
```

2. Make a call to a candidate:
```python
call = make_outbound_call(
    to_number="+1234567890",
    from_number="+0987654321",
    candidate_name="John Doe",
    position="Software Engineer"
)
```

## Interview Flow

1. Initial Verification
   - Confirms candidate identity
   - Verifies interest in position
   - Confirms good time to talk

2. Skills Assessment
   - Checks Trieve database for candidate info
   - Collects skills and experience if not found
   - Stores information in TinyDB

3. Experience Verification
   - Verifies work experience
   - Documents technical skills
   - Records years of experience

4. Professional Closing
   - Thanks candidate
   - Explains next steps
   - Ends call professionally

## Database Structure

The TinyDB database (`hr_database.json`) stores:
- Candidate information
- Skills and experience
- Interview notes
- Call outcomes

## API Integration

- Twilio: Handles voice calls
- Trieve.ai: Manages resume data
- TinyDB: Local data storage
