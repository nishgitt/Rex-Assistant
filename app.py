import os
import pypdf
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from openai import OpenAI, APIError

# Resolve absolute path to .env file relative to the app.py script
DOTENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(DOTENV_PATH, override=True)

app = Flask(__name__)

# Setup local storage folder for saving text context
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
CURRENT_MATERIAL_PATH = os.path.join(UPLOAD_FOLDER, 'current_material.txt')
CURRENT_MATERIAL_NAME_PATH = os.path.join(UPLOAD_FOLDER, 'current_material_name.txt')

def get_client():
    """
    Reloads environment variables and returns a Groq API client instance.
    Raises ValueError if API Key is not set or placeholder.
    """
    load_dotenv(DOTENV_PATH, override=True)
    api_key = os.getenv("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not api_key or api_key in ["YOUR_GROQ_API_KEY_HERE", "your_api_key_here"]:
        raise ValueError(
            "API key is not configured. Please set GROQ_API_KEY in your .env file."
        )
    return OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )

@app.route("/")
def home():
    """
    Serve the frontend dashboard templates.
    """
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload_file():
    """
    Route to process PDF or TXT upload and extract text contents.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file part in request."}), 400
        
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400
        
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    
    extracted_text = ""
    try:
        if ext == ".txt":
            extracted_text = file.read().decode("utf-8", errors="ignore")
        elif ext == ".pdf":
            reader = pypdf.PdfReader(file)
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            extracted_text = "\n\n--- Page Break ---\n\n".join(text_parts)
        else:
            return jsonify({"error": "Unsupported file format. Please upload a .txt or .pdf file."}), 400
            
        if not extracted_text.strip():
            return jsonify({"error": "No text content could be extracted from the file."}), 400
            
        # Cache extracted text locally to survive server reloads
        with open(CURRENT_MATERIAL_PATH, "w", encoding="utf-8") as f:
            f.write(extracted_text)
            
        # Cache the file name for display
        with open(CURRENT_MATERIAL_NAME_PATH, "w", encoding="utf-8") as f:
            f.write(filename)
            
        return jsonify({"message": f"Successfully processed and stored '{filename}'."})
        
    except Exception as e:
        return jsonify({"error": f"Failed to process file: {str(e)}"}), 500

@app.route("/ask", methods=["POST"])
def ask_question():
    """
    Query the cached study context with a student question using Gemini.
    """
    question = request.form.get("question")
    if not question:
        return jsonify({"error": "No question provided."}), 400
        
    if not os.path.exists(CURRENT_MATERIAL_PATH):
        return jsonify({"error": "No study material uploaded yet. Please upload a file first."}), 400
        
    try:
        # Load the extracted text
        with open(CURRENT_MATERIAL_PATH, "r", encoding="utf-8") as f:
            context = f.read()
            
        # Get filename
        filename = "Uploaded Document"
        if os.path.exists(CURRENT_MATERIAL_NAME_PATH):
            with open(CURRENT_MATERIAL_NAME_PATH, "r", encoding="utf-8") as f:
                filename = f.read().strip()
                
        # Initialize Groq Client dynamically (allows .env changes on the fly)
        try:
            client = get_client()
        except ValueError as ve:
            # Guide the student on how to set the API Key nicely in chat
            guide_msg = (
                f"⚠️ **Groq API Key missing or not configured.**\n\n"
                f"To query **{filename}**, please follow these steps:\n"
                f"1. Open the file `.env` inside the project folder (`Study Ass` on your Desktop).\n"
                f"2. Add your Groq API key: \n"
                f"   `GROQ_API_KEY=gsk_...`\n"
                f"3. Save the `.env` file and try sending your question again!\n\n"
                f"*Note: You can get a free key from the [Groq Console](https://console.groq.com/).*"
            )
            return jsonify({"answer": guide_msg}), 200
            
        # Construct LLM prompt
        prompt = f"""You are a helpful and intelligent AI Study Assistant.
Below is the content of the study material uploaded by the student (File: {filename}):

---------------------
{context}
---------------------

Using the study material above, answer the student's question: {question}

Guidelines:
1. Provide a detailed, clear, and structured answer.
2. Rely primarily on the provided study material. If the answer cannot be found in the material, use your general knowledge to answer, but explicitly state that it wasn't found in the text.
3. Use markdown formatting (bullet points, bold text, numbered lists, etc.) to make it easy to read and study.
"""

        # Query Groq LLM (Llama 3.3 70B)
        response = client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return jsonify({"answer": response.choices[0].message.content})
        
    except APIError as ae:
        error_msg = ae.message
        if "quota" in error_msg.lower() or "limit" in error_msg.lower():
            guide_msg = (
                "⚠️ **Groq API Quota / Limit Exceeded.**\n\n"
                "The API key configured has exceeded its rate limit or quota.\n\n"
                "To resolve this, check your account status on the [Groq Console](https://console.groq.com/) or update your key in `.env`."
            )
        else:
            guide_msg = f"⚠️ **API Error:**\n\n{error_msg}"
        return jsonify({"answer": guide_msg}), 200
    except Exception as e:
        return jsonify({"answer": f"⚠️ **Server error:**\n\n{str(e)}"}), 200

if __name__ == "__main__":
    app.run(port=5000, debug=True)