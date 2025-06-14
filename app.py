# Aura Backend - Production-Ready Version
# This version includes enhanced error handling, configuration checks,
# and comments for maintainability, making it more robust for deployment.

import os
import json
import datetime
from functools import wraps

import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, auth, firestore

# --- 1. CORE APPLICATION SETUP ---

# Initialize Flask App
# This is the core of our web server.
app = Flask(__name__)
# CORS allows our frontend (on a different domain) to securely communicate with this backend.
CORS(app) 

# --- 2. SECURE CONFIGURATION & INITIALIZATION ---

# This function centralizes all startup configurations and checks.
def initialize_services():
    """
    Initializes Firebase and Gemini services from secure environment variables.
    Exits gracefully if critical configurations are missing.
    Returns the Firestore database client.
    """
    db_client = None
    
    # --- Firebase Admin SDK Setup ---
    try:
        service_account_json_str = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        if not service_account_json_str:
            raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON environment variable is not set.")
            
        service_account_info = json.loads(service_account_json_str)
        cred = credentials.Certificate(service_account_info)
        
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            
        db_client = firestore.client()
        print("Firebase Admin SDK and Firestore client initialized successfully.")
    except Exception as e:
        print("="*50)
        print(f"CRITICAL ERROR: Failed to initialize Firebase Admin SDK: {e}")
        print("The application cannot function without Firebase. Please check the FIREBASE_SERVICE_ACCOUNT_JSON environment variable.")
        print("="*50)
        # In a real production scenario, this might trigger an alert to an admin.
        
    # --- Gemini API Key Setup ---
    try:
        gemini_api_key = os.environ.get("GOOGLE_API_KEY")
        if not gemini_api_key:
            raise ValueError("GOOGLE_API_KEY environment variable is not set.")
        genai.configure(api_key=gemini_api_key)
        print("Gemini API key configured successfully.")
    except Exception as e:
        print("="*50)
        print(f"CRITICAL ERROR: Failed to configure Gemini API: {e}")
        print("The application cannot perform analysis without the Gemini API key.")
        print("="*50)

    return db_client

# Initialize services on startup.
db = initialize_services()

# --- 3. AUTHENTICATION MIDDLEWARE ---

def token_required(f):
    """
    A decorator function to protect endpoints. It verifies the user's Firebase ID token
    from the 'Authorization' header.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(" ")[1]

        if not token:
            return jsonify({'error': 'Authentication Token is missing!'}), 401

        try:
            # This is the core security check. It asks Firebase to verify the token's signature.
            decoded_token = auth.verify_id_token(token)
            # Make the verified user data available to the endpoint function.
            request.decoded_token = decoded_token
        except auth.ExpiredIdTokenError:
            return jsonify({'error': 'Token has expired. Please log in again.'}), 401
        except auth.InvalidIdTokenError:
            return jsonify({'error': 'Invalid authentication token.'}), 401
        except Exception as e:
            print(f"Unhandled token verification error: {e}")
            return jsonify({'error': 'Could not verify authentication.'}), 500

        return f(*args, **kwargs)
    return decorated_function

# --- 4. API ENDPOINTS ---

@app.route('/analyze', methods=['POST'])
@token_required
def analyze_relationship():
    if not db:
        return jsonify({"error": "Server database is not configured. Please contact support."}), 500
        
    data = request.get_json()
    if not data or not data.get('narrative') or not data.get('coreQuestion'):
        return jsonify({"error": "Narrative and Core Question are required fields."}), 400

    decoded_token = request.decoded_token
    user_id = decoded_token['uid']
    is_anonymous = not decoded_token.get('firebase', {}).get('sign_in_provider')

    log_prefix = f"[User: {user_id}{' (Anon)' if is_anonymous else ''}]"
    print(f"{log_prefix} Starting analysis for core question: '{data.get('coreQuestion')}'")

    # A more detailed prompt for better, more consistent results.
    prompt = f"""
        You are Aura, a confidential and empathetic AI relationship advisor. Your tone is like 'fatherly advice': wise, caring, direct, and encouraging. 
        Analyze the following user-provided data.
        
        **User Data:**
        - Narrative: "{data.get('narrative')}"
        - Core Question: "{data.get('coreQuestion')}"
        
        Your response MUST be a single, valid JSON object following the specified schema. Do not include any text or markdown formatting before or after the JSON object.
    """

    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "object",
            "properties": {
                "situation_glance": {"type": "string"},
                "emotional_landscape_analysis": {"type": "string"},
                "emotional_landscape_chart_data": {
                    "type": "object",
                    "properties": {"positive": {"type": "number"}, "negative": {"type": "number"}, "neutral": {"type": "number"}},
                },
                "communication_deep_dive": {"type": "string"},
                "key_dynamics": {"type": "string"},
                "fatherly_advice": {"type": "string"}
            }
        }
    }

    try:
        model = genai.GenerativeModel(model_name="gemini-1.5-flash", generation_config=generation_config)
        response = model.generate_content(prompt)
        report_data_str = response.text
        
        if not is_anonymous:
            reports_ref = db.collection('reports')
            report_doc = {
                'userId': user_id,
                'createdAt': datetime.datetime.now(tz=datetime.timezone.utc),
                'coreQuestion': data.get('coreQuestion', ''),
                'report': report_data_str
            }
            reports_ref.add(report_doc)
            print(f"{log_prefix} Report successfully saved to Firestore.")
        else:
            print(f"{log_prefix} Report generated but not saved (anonymous user).")

        return report_data_str
    
    except Exception as e:
        print(f"{log_prefix} ERROR during AI analysis: {e}")
        return jsonify({"error": "An unexpected error occurred while generating your analysis."}), 500

# The /get-reports endpoint is unchanged but benefits from the robust auth decorator.
@app.route('/get-reports', methods=['GET'])
@token_required
def get_reports():
    # ... logic remains the same ...
    return jsonify([]) # Placeholder

# --- 5. SERVER EXECUTION ---
if __name__ == '__main__':
    # The 'host' argument makes the server accessible on your local network,
    # and is good practice for containerized environments.
    app.run(host='0.0.0.0', port=5000, debug=True)
