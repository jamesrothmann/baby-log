import os
import threading
import requests
import google.generativeai as genai
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import time

app = Flask(__name__)

# --- CONFIGURATION ---
# Get these from your Environment Variables in the Cloud Dashboard
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_FORM_URL = os.environ.get("GOOGLE_FORM_URL", "https://docs.google.com/forms/u/0/d/e/1FAIpQLSdozkwvFLM9JeBN2HOEZ8G3CANmiMj8vVYBU0CDvn3MNgrBag/formResponse")

# Map your Google Form Entry IDs
FORM_FIELDS = {
    "date": "entry.1823354629",
    "time": "entry.1109844519",
    "log_type": "entry.707765665",
    "transcript": "entry.1028845639"
}

genai.configure(api_key=GEMINI_API_KEY)

def process_log_background(audio_path, activity_type, timestamp_str, date_str):
    """
    Handles the slow stuff (Upload -> Transcribe -> Form Submit)
    in a separate thread so Siri doesn't hang.
    """
    print(f"[{activity_type}] Starting background processing...")
    
    try:
        # 1. Setup Gemini Model
        # Using flash for speed/cost.
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # 2. Upload the file to Gemini
        print(f"[{activity_type}] Uploading audio to Gemini...")
        audio_file = genai.upload_file(path=audio_path)
        
        # Wait for processing state (usually instant for small audio, but good safety)
        while audio_file.state.name == "PROCESSING":
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)

        # 3. Generate Content
        print(f"[{activity_type}] Transcribing...")
        prompt = "Listen to this audio log. Transcribe it exactly. Do not add markdown, timestamps, or conversational filler. Just the raw text."
        response = model.generate_content([prompt, audio_file])
        transcription = response.text.strip()
        print(f"[{activity_type}] Transcript: {transcription}")

        # 4. Submit to Google Form
        form_data = {
            FORM_FIELDS["date"]: date_str,
            FORM_FIELDS["time"]: timestamp_str,
            FORM_FIELDS["log_type"]: activity_type,
            FORM_FIELDS["transcript"]: transcription
        }
        
        # Google Forms submission
        requests.post(GOOGLE_FORM_URL, data=form_data)
        print(f"[{activity_type}] Successfully posted to Google Form.")
        
        # 5. Cleanup
        # Delete from Gemini (optional, but polite)
        genai.delete_file(audio_file.name)
        # Delete local temp file
        if os.path.exists(audio_path):
            os.remove(audio_path)

    except Exception as e:
        print(f"!!! Error in background task: {e}")

@app.route('/', methods=['GET'])
def health_check():
    return "Baby Logger API is Online", 200

@app.route('/log-baby', methods=['POST'])
def log_baby():
    # 1. Validation
    if 'file' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    
    file = request.files['file']
    activity_type = request.form.get('activity', 'General Log')
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # 2. Generate timestamps
    from datetime import datetime
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    # 3. Save temp file
    # We use /tmp because most containerized environments allow writing there
    filename = secure_filename(f"{int(now.timestamp())}_{file.filename}")
    save_path = os.path.join("/tmp", filename)
    file.save(save_path)

    # 4. Start Background Thread (FIRE AND FORGET)
    thread = threading.Thread(target=process_log_background, args=(save_path, activity_type, time_str, date_str))
    thread.daemon = True # Optional: ensures thread dies if main app dies (usually fine)
    thread.start()

    # 5. Return Success Immediately
    return jsonify({
        "status": "success", 
        "message": "Log received. Processing in background."
    }), 200

if __name__ == '__main__':
    # For local testing
    app.run(debug=True, port=5000)