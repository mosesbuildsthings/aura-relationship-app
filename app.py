# Aura Backend - Final Production Version
# This version is configured to run on a live server like Render.

import os
import json
import datetime
from functools import wraps

import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, auth, firestore
from dotenv import load_dotenv

# --- 1. CORE APPLICATION SETUP ---
load_dotenv() # Load environment variables from .env for local development
app = Flask(__name__)
# Configure CORS to allow requests from your frontend's domain
# For production, you might want to restrict this to your actual frontend URL
CORS(app) 

# --- 2. SECURE CONFIGURATION & INITIALIZATION ---
db = None
try:
    # Service account key is loaded securely from an environment variable
    service_account_json_str = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not service_account_json_str:
        raise ValueError("CRITICAL: FIREBASE_SERVICE_ACCOUNT_JSON environment variable is not set.")
    
    service_account_info = json.loads(service_account_json_str)
    cred = credentials.Certificate(service_account_info)
    
    # Prevents re-initializing the app on hot reloads
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
        
    db = firestore.client()
    print("Firebase Admin SDK and Firestore client initialized successfully.")

except Exception as e:
    print(f"CRITICAL ERROR: Failed to initialize Firebase Admin SDK: {e}")

try:
    # Gemini API key is loaded from an environment variable
    gemini_api_key = os.environ.get("GOOGLE_API_KEY")
    if not gemini_api_key:
        raise ValueError("CRITICAL: GOOGLE_API_KEY environment variable not set.")
    genai.configure(api_key=gemini_api_key)
    print("Gemini API key configured successfully.")
except Exception as e:
    print(f"CRITICAL ERROR: {e}")


# --- 3. AUTHENTICATION MIDDLEWARE ---
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers and request.headers['Authorization'].startswith('Bearer '):
            token = request.headers['Authorization'].split(' ')[1]

        if not token:
            return jsonify({'error': 'Authentication token is missing!'}), 401

        try:
            # Verify the token using the Firebase Admin SDK
            decoded_token = auth.verify_id_token(token)
            # Pass the user's unique ID (uid) to the decorated function
            kwargs['uid'] = decoded_token['uid']
        except auth.InvalidIdTokenError:
            return jsonify({'error': 'Invalid authentication token!'}), 403
        except Exception as e:
            return jsonify({'error': f'Authentication error: {e}'}), 500

        return f(*args, **kwargs)
    return decorated_function

# --- 4. API ENDPOINTS ---

@app.route('/analyze', methods=['POST'])
@token_required
def analyze_relationship(uid):
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request body."}), 400

    narrative = data.get('narrative', '')
    core_question = data.get('core_question')
    report_details = data.get('report_details', [])
    # media_files = data.get('media_files', []) # Future use

    if not core_question:
        return jsonify({"error": "The core question is required."}), 400
    if not narrative:
        return jsonify({"error": "The narrative is required."}), 400

    try:
        model = genai.GenerativeModel('gemini-pro')
        
        # Constructing a detailed prompt for better results
        prompt = f"""
        As an expert relationship analyst AI named Aura, generate a comprehensive report in HTML format.
        The user wants to understand the following situation.

        **Core Question:** {core_question}

        **User's Narrative:**
        "{narrative}"

        **Requested Analysis Points:** {', '.join(report_details)}

        **Instructions:**
        1.  Structure the response as a clean, well-formatted HTML document. Use headings (<h3>), paragraphs (<p>), and lists (<ul>, <li>).
        2.  Directly address the user's Core Question with a clear, summary answer first.
        3.  For each requested analysis point (e.g., "Communication Patterns", "Emotional Tone"), create a dedicated section.
        4.  Provide insightful, empathetic, and actionable advice. Maintain a supportive and objective tone.
        5.  Do not include `<html>`, `<head>`, or `<body>` tags. Only provide the inner content for a div.
        """

        response = model.generate_content(prompt)
        html_report = response.text

        # Save the report to Firestore
        report_data = {
            'uid': uid,
            'title': core_question,
            'narrative': narrative,
            'report_details': report_details,
            'html_report': html_report,
            'created_at': firestore.SERVER_TIMESTAMP
        }
        
        # Add a new document with a generated ID to the user's reports subcollection
        user_reports_ref = db.collection('users').document(uid).collection('reports')
        user_reports_ref.add(report_data)

        return jsonify({"html_report": html_report})

    except Exception as e:
        print(f"ERROR: Gemini API or Firestore error: {e}")
        return jsonify({"error": f"An internal error occurred during analysis: {e}"}), 500


@app.route('/get-reports', methods=['GET'])
@token_required
def get_reports(uid):
    try:
        user_reports_ref = db.collection('users').document(uid).collection('reports')
        # Order by creation date, newest first
        query = user_reports_ref.order_by('created_at', direction=firestore.Query.DESCENDING)
        reports = query.stream()

        reports_list = []
        for report in reports:
            report_data = report.to_dict()
            reports_list.append({
                'id': report.id,
                'title': report_data.get('title'),
                # Format timestamp for display
                'created_at': report_data.get('created_at').strftime('%B %d, %Y')
            })
        
        return jsonify(reports_list)
    except Exception as e:
        print(f"ERROR: Could not fetch reports: {e}")
        return jsonify({"error": "Failed to retrieve reports."}), 500


@app.route('/get-report/<report_id>', methods=['GET'])
@token_required
def get_report(uid, report_id):
    try:
        report_ref = db.collection('users').document(uid).collection('reports').document(report_id)
        report = report_ref.get()

        if not report.exists:
            return jsonify({"error": "Report not found or access denied."}), 404
        
        report_data = report.to_dict()
        return jsonify({
            "html_report": report_data.get("html_report")
        })

    except Exception as e:
        print(f"ERROR: Could not fetch single report: {e}")
        return jsonify({"error": "Failed to retrieve report."}), 500


# --- 5. SERVER EXECUTION ---
if __name__ == '__main__':
    # Use debug=True only for local development. Render will use gunicorn.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)
