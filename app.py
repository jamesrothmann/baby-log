import os
import threading
import requests
import base64
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from google import genai
from google.genai import types

app = Flask(__name__)

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_FORM_URL = os.environ.get("GOOGLE_FORM_URL", "https://docs.google.com/forms/u/0/d/e/1FAIpQLSdozkwvFLM9JeBN2HOEZ8G3CANmiMj8vVYBU0CDvn3MNgrBag/formResponse")

# Map your Google Form Entry IDs
FORM_FIELDS = {
    "date": "entry.1823354629",
    "time": "entry.1109844519",
    "log_type": "entry.707765665",
    "transcript": "entry.1028845639"
}

def process_log_background(audio_path, timestamp_str, date_str):
    print(f"Starting smart processing with gemini-flash-latest...")
    
    try:
        # 1. Initialize the new Client
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # 2. Prepare the Audio Data
        # We read the bytes and send them inline. 
        # For <20MB files, this is faster than the upload/delete method.
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        # 3. Define the Prompt
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

        # 4. call the API with Schema (Structured Output)
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

        # 5. Get the parsed data directly
        # The SDK automatically handles the JSON parsing now!
        result = response.parsed
        
        detected_category = result.get("LogType", "General Baby Log")
        detected_transcript = result.get("Recording Transcript", "")
        
        print(f"Detected: {detected_category} | Text: {detected_transcript}")

        # 6. Submit to Google Form
        form_data = {
            FORM_FIELDS["date"]: date_str,
            FORM_FIELDS["time"]: timestamp_str,
            FORM_FIELDS["log_type"]: detected_category,
            FORM_FIELDS["transcript"]: detected_transcript
        }
        
        requests.post(GOOGLE_FORM_URL, data=form_data)
        print(f"Successfully posted to Google Form.")
        
        # 7. Cleanup
        if os.path.exists(audio_path):
            os.remove(audio_path)

    except Exception as e:
        print(f"!!! Error in background task: {e}")
        # Clean up file even if error
        if os.path.exists(audio_path):
            os.remove(audio_path)

@app.route('/', methods=['GET'])
def health_check():
    return "Baby Log API (Flash Latest) is Online", 200

@app.route('/log-baby', methods=['POST'])
def log_baby():
    if 'file' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # Timestamp generation
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
