# Aura Backend Starter Kit
# This is a simple server that acts as a secure intermediary between your 
# frontend (index.html) and the Google Gemini API.

# --- 1. Installation ---
# Before you run this, you need to install Flask and Google's Generative AI library.
# Open your computer's terminal or command prompt and run these commands:
# pip install Flask
# pip install Flask-Cors
# pip install google-generativeai

import os
import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS

# --- 2. Configuration ---
# Your secret API key should be stored as an environment variable for security,
# not hardcoded. We'll get to that in the setup guide. For now, you can
# temporarily paste it here for testing if needed.
# It's recommended to set this in your terminal before running:
# For Mac/Linux: export GOOGLE_API_KEY='YOUR_API_KEY'
# For Windows: set GOOGLE_API_KEY='YOUR_API_KEY'
try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
except KeyError:
    print("="*50)
    print("ERROR: GOOGLE_API_KEY environment variable not set.")
    print("Please set the key in your terminal before running.")
    print("="*50)
    # For initial local testing, you can uncomment the line below and paste your key
    # genai.configure(api_key="PASTE_YOUR_GEMINI_API_KEY_HERE")


# --- 3. Flask App Initialization ---
app = Flask(__name__)
# CORS is needed to allow your index.html file (running on a different "origin")
# to communicate with this server.
CORS(app) 

# --- 4. The Analysis API Endpoint ---
# This is the URL that your frontend will send requests to.
@app.route('/analyze', methods=['POST'])
def analyze_relationship():
    """
    Receives relationship data from the frontend, sends it to the Gemini API,
    and returns the AI-generated report.
    """
    # Get the user's data from the incoming request
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid input"}), 400

    # Extract data (with fallbacks)
    narrative = data.get('narrative', '')
    core_question = data.get('coreQuestion', '')
    
    # Construct the detailed prompt for the AI
    prompt = f"""
        You are Aura, a confidential and empathetic AI relationship advisor as described in the blueprint document. Your tone should be like 'fatherly advice': wise, caring, direct, and encouraging. 
        
        Analyze the following user-provided data and generate a comprehensive relationship report.

        **User Data:**
        - Narrative: "{narrative}"
        - Core Question: "{core_question}"
        - Relationship Status: {data.get('relationshipStatus', 'N/A')}
        - Primary Challenges: {', '.join(data.get('primaryChallenges', [])) or 'None specified'}
        - User's Age: {data.get('yourAge', 'N/A')}
        - Partner's Age: {data.get('partnerAge', 'N/A')}
        - Children Involved: {'Yes' if data.get('childrenInvolved') else 'No'}
        - Children From: {data.get('childrenFrom', 'N/A')}
        - Co-parenting with Ex: {'Yes' if data.get('coParenting') else 'No'}

        Your response MUST be a single, valid JSON object that follows the specified schema, containing the full text for each chapter of the report.
    """

    # Define the generation config for a structured JSON response
    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "object",
            "properties": {
                "situation_glance": {"type": "string"},
                "emotional_landscape_analysis": {"type": "string"},
                "emotional_landscape_chart_data": {
                    "type": "object",
                    "properties": {
                        "positive": {"type": "number"},
                        "negative": {"type": "number"},
                        "neutral": {"type": "number"}
                    },
                    "required": ["positive", "negative", "neutral"]
                },
                "communication_deep_dive": {"type": "string"},
                "key_dynamics": {"type": "string"},
                "fatherly_advice": {"type": "string"}
            }
        }
    }

    try:
        # Initialize the Gemini model
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config
        )
        # Send the prompt to the model
        response = model.generate_content(prompt)
        
        # Return the AI's response to the frontend
        return response.text
    
    except Exception as e:
        # Handle potential errors (e.g., API key issue, network problem)
        print(f"An error occurred: {e}")
        return jsonify({"error": "An error occurred while communicating with the AI service."}), 500

# --- 5. Running the Server ---
if __name__ == '__main__':
    # This makes the server run when you execute the file directly.
    # The debug=True flag is useful for development as it automatically
    # reloads the server when you make changes.
    app.run(debug=True, port=5000)
