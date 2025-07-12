# -*- coding: utf-8 -*-
"""
Backend Flask server for the Aura Relationship Intelligence Platform.

This application provides a secure API for users to analyze relationship
narratives using Google's Gemini API and to save/retrieve reports
from a Cloud Firestore database. It handles user authentication via
Firebase Authentication.
"""
import os
import json
from functools import wraps
import io

import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, auth, firestore
from google.api_core import exceptions as google_exceptions
from dotenv import load_dotenv
from PIL import Image

# --- 1. CORE APPLICATION SETUP ---
# Load environment variables from a .env file for local development.
# In production (e.g., on Render), these will be set in the dashboard.
load_dotenv()
app = Flask(__name__)
# Configure Cross-Origin Resource Sharing (CORS) to allow the frontend
# to communicate with this backend.
CORS(app)

# --- 2. SECURE CONFIGURATION & INITIALIZATION ---
db = None
try:
    # The service account key is loaded securely from an environment variable.
    # This avoids hardcoding sensitive credentials in the source code.
    service_account_json_str = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not service_account_json_str:
        raise ValueError(
            "CRITICAL: FIREBASE_SERVICE_ACCOUNT_JSON environment variable is not set."
        )

    service_account_info = json.loads(service_account_json_str)
    cred = credentials.Certificate(service_account_info)

    # This check prevents re-initializing the app on hot reloads during development.
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    print("Firebase Admin SDK and Firestore client initialized successfully.")

except (ValueError, json.JSONDecodeError) as e:
    print(f"CRITICAL CONFIGURATION ERROR: {e}")
except Exception as e:
    print(f"CRITICAL ERROR: Failed to initialize Firebase Admin SDK: {e}")

try:
    # The Gemini API key is also loaded from a secure environment variable.
    gemini_api_key = os.environ.get("GOOGLE_API_KEY")
    if not gemini_api_key:
        raise ValueError("CRITICAL: GOOGLE_API_KEY environment variable is not set.")
    genai.configure(api_key=gemini_api_key)
    print("Gemini API key configured successfully.")
except ValueError as e:
    print(f"CRITICAL CONFIGURATION ERROR: {e}")


# --- 3. AUTHENTICATION MIDDLEWARE ---
def token_required(f):
    """Decorator to protect routes with Firebase JWT authentication."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        """Verifies the Firebase ID token from the Authorization header."""
        token = None
        # The token is expected in the 'Authorization' header as 'Bearer <token>'.
        if "Authorization" in request.headers and request.headers[
            "Authorization"
        ].startswith("Bearer "):
            token = request.headers["Authorization"].split(" ")[1]

        if not token:
            return jsonify({"error": "Authentication token is missing!"}), 401

        try:
            # Use Firebase Admin SDK to verify the token's validity.
            decoded_token = auth.verify_id_token(token)
            # Pass the user's unique ID (uid) to the protected route.
            kwargs["uid"] = decoded_token["uid"]
        except auth.InvalidIdTokenError:
            return jsonify({"error": "Invalid authentication token!"}), 403
        except Exception as e:
            return jsonify({"error": f"Authentication error: {e}"}), 500

        return f(*args, **kwargs)

    return decorated_function


# --- 4. API ENDPOINTS ---
@app.route("/analyze", methods=["POST"])
@token_required
def analyze_relationship(uid):
    """
    Analyzes a user-submitted narrative and optional images using the Gemini API 
    and saves the report. Handles multipart/form-data.
    """
    if 'narrative' not in request.form or 'core_question' not in request.form:
        return jsonify({"error": "Narrative and core question are required."}), 400

    narrative = request.form.get("narrative", "")
    core_question = request.form.get("core_question")
    report_details_str = request.form.get("report_details", "[]")
    report_details = json.loads(report_details_str)
    
    # Use getlist() to correctly handle multiple file uploads with the same field name.
    image_files = request.files.getlist('media')

    if not core_question or not narrative:
        return jsonify({"error": "Narrative and core question are required."}), 400

    try:
        # Initialize the Gemini model.
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Construct the prompt for the Gemini API, providing clear instructions.
        prompt_parts = [
            "As an expert relationship analyst AI named Aura, generate a comprehensive report in HTML format.",
            f"The user wants to understand the following situation.",
            f"**Core Question:** {core_question}",
            f"**User's Narrative:** \"{narrative}\"",
            f"**Requested Analysis Points:** {', '.join(report_details)}",
            "**Instructions:**",
            "1.  Structure the response as a clean, well-formatted HTML document. Use headings (<h3>), paragraphs (<p>), and lists (<ul>, <li>).",
            "2.  Directly address the user's Core Question with a clear, summary answer first.",
            "3.  For each requested analysis point, create a dedicated section.",
            "4.  Provide insightful, empathetic, and actionable advice. Maintain a supportive and objective tone.",
            "5.  Do not include `<html>`, `<head>`, or `<body>` tags. Only provide the inner content for a div."
        ]
        
        # Loop through uploaded files and add them to the prompt parts for multi-modal analysis.
        if image_files and image_files[0].filename:
            prompt_parts.append("\n**Image Analysis:** Analyze the attached images in the context of the user's narrative and question.")
            for image_file in image_files:
                try:
                    # Use PIL to open the image from the file stream.
                    img = Image.open(image_file.stream)
                    prompt_parts.append(img)
                except Exception as e:
                    print(f"Warning: Could not process an image file: {e}")


        # Generate the report content using the Gemini API.
        response = model.generate_content(prompt_parts)
        html_report = response.text

        # Prepare the data to be saved to Firestore.
        report_data = {
            "uid": uid,
            "title": core_question,
            "narrative": narrative,
            "report_details": report_details,
            "html_report": html_report,
            "created_at": firestore.SERVER_TIMESTAMP,
        }

        # Save the new report to a 'reports' subcollection under the user's document.
        user_reports_ref = db.collection("users").document(uid).collection("reports")
        user_reports_ref.add(report_data)

        # Return the generated HTML report to the frontend.
        return jsonify({"html_report": html_report})

    except google_exceptions.GoogleAPICallError as e:
        print(f"ERROR: Gemini API call failed: {e}")
        return jsonify({"error": "The analysis engine is currently unavailable."}), 503
    except Exception as e:
        print(f"ERROR: An unexpected error occurred in /analyze: {e}")
        return jsonify({"error": "An internal error occurred during analysis."}), 500


@app.route("/get-reports", methods=["GET"])
@token_required
def get_reports(uid):
    """
    Retrieves a list of all reports for the authenticated user.
    """
    try:
        user_reports_ref = db.collection("users").document(uid).collection("reports")
        # Order reports by creation date, newest first.
        query = user_reports_ref.order_by(
            "created_at", direction=firestore.Query.DESCENDING
        )
        reports = query.stream()

        reports_list = []
        for report in reports:
            report_data = report.to_dict()
            creation_time = report_data.get("created_at")
            reports_list.append(
                {
                    "id": report.id,
                    "title": report_data.get("title"),
                    # Format the timestamp for display on the frontend.
                    "created_at": creation_time.strftime("%B %d, %Y")
                    if creation_time
                    else None,
                }
            )

        return jsonify(reports_list)
    except Exception as e:
        print(f"ERROR: Could not fetch reports for UID {uid}: {e}")
        return jsonify({"error": "Failed to retrieve reports."}), 500


@app.route("/get-report/<report_id>", methods=["GET"])
@token_required
def get_report(uid, report_id):
    """
    Retrieves the HTML content of a single, specific report.
    """
    try:
        report_ref = (
            db.collection("users").document(uid).collection("reports").document(report_id)
        )
        report = report_ref.get()

        if not report.exists:
            return jsonify({"error": "Report not found or access denied."}), 404

        report_data = report.to_dict()
        return jsonify({"html_report": report_data.get("html_report")})

    except Exception as e:
        print(f"ERROR: Could not fetch report {report_id} for UID {uid}: {e}")
        return jsonify({"error": "Failed to retrieve report."}), 500


# --- 5. SERVER EXECUTION ---
if __name__ == "__main__":
    # Use debug=False for production. Gunicorn will be used by Render.
    # The port is read from the environment, defaulting to 10000 for services like Render.
    app.run(
        host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=True
    )
