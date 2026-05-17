
# ☁️ Professional Cloud Server API v2.0

Self-Hosted File Storage REST API with Automatic Ngrok Integration

## Features
- Public HTTPS Access via Ngrok
- File Upload / Download API
- Folder Management
- Multiple File Upload
- Disk Space Monitoring
- REST API Endpoints
- .env Configuration
- Cross Platform Support
- Lightweight & Fast

## Installation

1. Install Python 3.10+
2. Install dependencies:

pip install flask flask-cors werkzeug psutil pyngrok Pillow python-dotenv

3. Run the server:

python app.py

## Ngrok Setup

Step 1:
Create a free account:
https://ngrok.com

Step 2:
Copy your Auth Token:
https://dashboard.ngrok.com/get-started/your-authtoken

Step 3:
Create a .env file:

NGROK_AUTH_TOKEN=your_token_here
NGROK_ENABLED=true
SERVER_PORT=5000

Step 4:
Run the server:

python app.py

Your public server URL will appear automatically.

## API Endpoints

GET    /api/storage
GET    /api/files
POST   /api/upload
POST   /api/upload/multiple
GET    /api/files/{id}
DELETE /api/files/{id}
GET    /api/folders
POST   /api/folders
DELETE /api/folders/{id}
GET    /api/ngrok/status
POST   /api/ngrok/reconnect

## Example Usage

Python:
requests.post(f"{BASE}/api/upload", files={"file": open("photo.jpg","rb")})

cURL:
curl -X POST YOUR_URL/api/upload -F "file=@photo.jpg"

JavaScript:
fetch('YOUR_URL/api/upload', {method:'POST', body:formData})

## Security Recommendations
- Add JWT Authentication
- Use HTTPS
- Enable Rate Limiting
- Restrict File Types
- Add API Keys

## Project Structure

cloud-server/
│
├── app.py
├── .env
├── requirements.txt
├── uploads/
├── logs/
└── README.md
