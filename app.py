import os
import threading
import requests
import json
import csv
import io
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from google import genai
from google.genai import types

app = Flask(__name__)

# --- CONFIGURATION ---
# Get these from your Render Environment Variables
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_FORM_URL = os.environ.get("GOOGLE_FORM_URL", "https://docs.google.com/forms/u/0/d/e/1FAIpQLSdozkwvFLM9JeBN2HOEZ8G3CANmiMj8vVYBU0CDvn3MNgrBag/formResponse")
# Your Public Google Sheet CSV Link
PUBLIC_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRjXQMvgqAVFHULl2WbNNyOI9MzAPsbShbXVgh2KkbGRhX7LLZjKVf-58oXsIwpkA8XUffIl8_pdIj9/pub?gid=355169254&single=true&output=csv"

# Map your Google Form Entry IDs
FORM_FIELDS = {
    "date": "entry.1823354629",
    "time": "entry.1109844519",
    "log_type": "entry.707765665",
    "transcript": "entry.1028845639"
}

# --- HELPER FUNCTIONS ---

def process_log_background(audio_path, timestamp_str, date_str):
    """
    Background task for Voice Logs:
    1. Sends audio to Gemini Flash.
    2. Classifies and Transcribes.
    3. Posts to Google Form.
    """
    print(f"Starting smart voice processing...")
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Read audio file
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        prompt_text = """
        You are a baby logging assistant. Listen to this audio and extract the data.
        Classify the "LogType" into exactly one of these:
        - Breastfeeding Left
        - Breastfeeding Right
        - Breastfeeding Pause
        - Breastfeeding Unpause
        - Nappy Change
        - Start Burping
        - Stop Burping
        - General Baby Log
        (Default to General Baby Log if unsure)
        """

        # Call Gemini with Structured Output Schema
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt_text),
                        types.Part.from_bytes(data=audio_bytes, mime_type="audio/m4a"),
                    ],
                ),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    required=["LogType", "Recording Transcript"],
                    properties={
                        "LogType": types.Schema(type=types.Type.STRING),
                        "Recording Transcript": types.Schema(type=types.Type.STRING),
                    },
                ),
            ),
        )

        result = response.parsed
        detected_category = result.get("LogType", "General Baby Log")
        detected_transcript = result.get("Recording Transcript", "")
        
        print(f"Detected: {detected_category} | Text: {detected_transcript}")

        # Post to Google Form
        form_data = {
            FORM_FIELDS["date"]: date_str,
            FORM_FIELDS["time"]: timestamp_str,
            FORM_FIELDS["log_type"]: detected_category,
            FORM_FIELDS["transcript"]: detected_transcript
        }
        
        requests.post(GOOGLE_FORM_URL, data=form_data)
        print(f"Successfully posted Voice Log to Google Form.")
        
        # Cleanup temp file
        if os.path.exists(audio_path):
            os.remove(audio_path)

    except Exception as e:
        print(f"!!! Error in background voice task: {e}")
        if os.path.exists(audio_path):
            os.remove(audio_path)

# --- ROUTES ---

@app.route('/', methods=['GET'])
def dashboard():
    """Renders the HTML Dashboard"""
    return render_template('dashboard.html')

@app.route('/api/data', methods=['GET'])
def get_data():
    """Proxies the Google Sheet CSV to avoid CORS issues on the frontend"""
    try:
        response = requests.get(PUBLIC_CSV_URL)
        return response.content, 200, {'Content-Type': 'text/csv'}
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/log-button', methods=['POST'])
def log_button():
    """
    Endpoint for Manual iOS Widgets (No Audio).
    Expects JSON: { "type": "Nappy Change", "note": "optional" }
    """
    data = request.json
    if not data or 'type' not in data:
        return jsonify({"error": "No log type provided"}), 400
    
    log_type = data['type'] # e.g., "Breastfeeding Left"
    note = data.get('note', '')

    # Generate Timestamps
    from datetime import datetime
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M") # HH:MM format

    # Submit to Google Form directly
    try:
        form_data = {
            FORM_FIELDS["date"]: date_str,
            FORM_FIELDS["time"]: time_str,
            FORM_FIELDS["log_type"]: log_type,
            FORM_FIELDS["transcript"]: note or "Manual Button Log"
        }
        
        requests.post(GOOGLE_FORM_URL, data=form_data)
        print(f"Button Log Success: {log_type}")
        return jsonify({"status": "success", "message": f"Logged: {log_type}"}), 200

    except Exception as e:
        print(f"Error logging button: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/log-baby', methods=['POST'])
def log_baby():
    """
    Endpoint for Voice Shortcuts.
    Accepts an audio file, processes it in the background using Gemini.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # Generate Timestamps
    from datetime import datetime
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    # Save temp file
    filename = secure_filename(f"{int(now.timestamp())}_{file.filename}")
    save_path = os.path.join("/tmp", filename)
    file.save(save_path)

    # Start Background Thread
    thread = threading.Thread(target=process_log_background, args=(save_path, time_str, date_str))
    thread.daemon = True
    thread.start()

    return jsonify({"status": "success", "message": "Processing..."}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)
