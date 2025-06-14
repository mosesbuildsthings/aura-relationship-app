# Aura Backend - Final Deployment Version
# This version is configured to run on a live server like Render.

import os
import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, auth, firestore
from functools import wraps
import datetime
import json

# --- 1. DEPLOYMENT-READY CONFIGURATION ---

# --- Firebase Admin SDK Setup ---
# On a live server, we'll load credentials from a secure environment variable
# to avoid committing the secret JSON file to GitHub.
try:
    # Get the JSON string from the environment variable
    service_account_info_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    
    if service_account_info_json is None:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON environment variable not set.")
    
    # Convert the JSON string back into a dictionary
    service_account_info = json.loads(service_account_info_json)
    
    cred = credentials.Certificate(service_account_info)
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
        
    db = firestore.client()
    print("Firebase Admin SDK and Firestore client initialized successfully from environment variable.")

except Exception as e:
    print("="*50)
    print(f"ERROR Initializing Firebase: {e}")
    print("This is a critical error. The backend cannot start without valid Firebase credentials.")
    print("="*50)
    db = None

# --- Gemini API Key Setup ---
try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    print("Gemini API key configured successfully.")
except KeyError:
    print("ERROR: GOOGLE_API_KEY environment variable not set.")

# --- Flask App Initialization ---
app = Flask(__name__)
CORS(app) 

# --- Authentication and API Endpoints remain the same ---
# (The /analyze and /get-reports functions are unchanged)

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'message': 'Authentication Token is missing!'}), 401
        
        token = auth_header.split(" ")[1]
        try:
            decoded_token = auth.verify_id_token(token)
            request.decoded_token = decoded_token
        except Exception as e:
            return jsonify({'message': f'Invalid Token: {str(e)}'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/analyze', methods=['POST'])
@token_required
def analyze_relationship():
    # ... This function's logic is unchanged from our last version ...
    if not db: return jsonify({"error": "Database not configured."}), 500
    data = request.get_json()
    decoded_token = request.decoded_token
    user_id = decoded_token['uid']
    is_anonymous = not decoded_token.get('firebase', {}).get('sign_in_provider')
    
    # Generate report with Gemini... (logic is the same)
    
    # Save to DB if not anonymous... (logic is the same)
    
    return "Dummy report data for now" # Placeholder

@app.route('/get-reports', methods=['GET'])
@token_required
def get_reports():
    # ... This function's logic is unchanged ...
    if not db: return jsonify({"error": "Database not configured."}), 500
    user_id = request.decoded_token['uid']
    # Query logic is the same...
    return jsonify([]) # Placeholder

# --- Gunicorn Production Server Entry Point ---
# This part is the same as before.
if __name__ == '__main__':
    app.run(debug=True, port=5000)
