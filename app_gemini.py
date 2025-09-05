from flask import Flask, request, jsonify
from flask_cors import CORS
import PyPDF2
import random
import google.generativeai as genai
import json
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Updated CORS configuration to handle dynamic Netlify URLs
CORS(app, 
     origins=[
         "http://127.0.0.1:5500",
         "https://sample-render-hosting-1.onrender.com",
         "https://paufrancisco.github.io",
         "https://quizton-lake.vercel.app",
     ],
     methods=['GET', 'POST', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization'],
     supports_credentials=True
)

# Add explicit preflight handling for OPTIONS requests
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "*")
        response.headers.add('Access-Control-Allow-Methods', "*")
        return response

# Add CORS headers to all responses with dynamic origin support
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    
    # List of explicitly allowed origins
    allowed_origins = [
        "http://127.0.0.1:5500",
        "https://sample-render-hosting-1.onrender.com",
        "https://paufrancisco.github.io",
        "https://quizton-lake.vercel.app",
    ]
    
    # Allow the origin if it's in our list OR if it's a netlify.app or vercel.app domain
    if origin in allowed_origins or (origin and (origin.endswith('.netlify.app') or origin.endswith('.vercel.app'))):
        response.headers.add('Access-Control-Allow-Origin', origin)
    
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# Initialize Gemini client
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Warning: Gemini API key not found")
    model = None
else:
    genai.configure(api_key=api_key)
    
    # Use gemini-2.0-flash as shown in your dashboard
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        test_response = model.generate_content("Hello!")
        print("Gemini client initialized successfully with model: gemini-2.0-flash")
        print(f"Test response: {test_response.text[:50]}...")
    except Exception as e:
        print(f"Error testing Gemini client: {e}")
        model = None

def romanize(num):
    roman_numerals = ['I', 'II', 'III']
    return roman_numerals[num - 1] if 1 <= num <= 3 else str(num)

def generate_questions_with_gemini(text, question_type, difficulty, num_questions):
    """Generate questions using Google Gemini based on PDF content"""
    
    # If model is not available, use fallback
    if not model:
        print("Gemini model not available, using fallback questions")
        return generate_fallback_questions(question_type, num_questions)
    
    # Create prompts based on question type
    if question_type == 'multiple-choice':
        prompt = f"""
        Based on the following text, generate {num_questions} multiple-choice questions with difficulty level: {difficulty}.
        
        Text: {text[:3000]}
        
        Requirements:
        - Generate exactly {num_questions} questions
        - Difficulty: {difficulty} (easy = basic comprehension, medium = analysis, hard = synthesis/evaluation)
        - Each question should have 4 choices (A, B, C, D)
        - Questions should be directly answerable from the text
        - Include the correct answer
        
        Format your response as a JSON array like this:
        [
            {{
                "question": "Question text here?",
                "choices": {{
                    "A": "Choice A text",
                    "B": "Choice B text", 
                    "C": "Choice C text",
                    "D": "Choice D text"
                }},
                "correct_answer": "A"
            }}
        ]
        
        Return only the JSON array, no additional text.
        """
    
    elif question_type == 'true-false':
        prompt = f"""
        Based on the following text, generate {num_questions} true/false questions with difficulty level: {difficulty}.
        
        Text: {text[:3000]}
        
        Requirements:
        - Generate exactly {num_questions} questions
        - Difficulty: {difficulty}
        - Questions should test understanding of the text
        - Include the correct answer (True or False)
        
        Format your response as a JSON array like this:
        [
            {{
                "question": "Statement to evaluate as true or false",
                "correct_answer": "True"
            }}
        ]
        
        Return only the JSON array, no additional text.
        """
    
    elif question_type == 'fill-blank':
        prompt = f"""
        Based on the following text, generate {num_questions} fill-in-the-blank questions with difficulty level: {difficulty}.
        
        Text: {text[:3000]}
        
        Requirements:
        - Generate exactly {num_questions} questions
        - Difficulty: {difficulty}
        - Use underscores (____) to indicate blanks
        - Questions should test key concepts from the text
        - Include the correct answer
        
        Format your response as a JSON array like this:
        [
            {{
                "question": "The ____ is an important concept in this text.",
                "correct_answer": "correct word or phrase"
            }}
        ]
        
        Return only the JSON array, no additional text.
        """
    
    try:
        response = model.generate_content(prompt)
        
        # Clean the response text (remove markdown code blocks if present)
        response_text = response.text.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        # Parse the JSON response
        questions_data = json.loads(response_text)
        return questions_data
        
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}")
        print(f"Raw response: {response.text if 'response' in locals() else 'No response'}")
        return generate_fallback_questions(question_type, num_questions)
    except Exception as e:
        print(f"Error generating questions: {e}")
        return generate_fallback_questions(question_type, num_questions)

def generate_fallback_questions(question_type, num_questions):
    """Generate fallback questions if Gemini API fails"""
    questions = []
    
    for i in range(1, num_questions + 1):
        if question_type == 'multiple-choice':
            questions.append({
                "question": f"Sample question {i} (API unavailable)",
                "choices": {
                    "A": f"Choice A for Question {i}",
                    "B": f"Choice B for Question {i}",
                    "C": f"Choice C for Question {i}",
                    "D": f"Choice D for Question {i}"
                },
                "correct_answer": random.choice(['A', 'B', 'C', 'D'])
            })
        elif question_type == 'true-false':
            questions.append({
                "question": f"Sample true/false statement {i} (API unavailable)",
                "correct_answer": random.choice(['True', 'False'])
            })
        elif question_type == 'fill-blank':
            questions.append({
                "question": f"Fill in the blank {i}: _____ (API unavailable)",
                "correct_answer": f"Answer{i}"
            })
    
    return questions

@app.route('/convert', methods=['POST'])
def convert():
    file = request.files.get('files[]')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    try:
        # Extract text from PDF
        pdf_reader = PyPDF2.PdfReader(file)
        text = ''.join([page.extract_text() or '' for page in pdf_reader.pages])
        
        if not text.strip():
            return jsonify({'error': 'No text could be extracted from the PDF'}), 400

        num_sets = int(request.form.get('numSets'))
        num_sets = min(num_sets, 3)  # Limit to a max of 3 parts

        sets = []

        for i in range(1, num_sets + 1):
            set_questions = int(request.form.get(f'set-{i}-questions'))
            difficulty = request.form.get(f'set-{i}-difficulty')
            question_type = request.form.get(f'set-{i}-question-type')

            # Generate questions using Gemini
            generated_questions = generate_questions_with_gemini(
                text, question_type, difficulty, set_questions
            )

            questions = []
            answers = []

            for idx, q_data in enumerate(generated_questions[:set_questions], 1):
                if question_type == 'multiple-choice':
                    questions.append({
                        "number": idx,
                        "question": q_data.get("question", f"Question {idx}"),
                        "choices": q_data.get("choices", {})
                    })
                    answers.append(f"{idx}. {q_data.get('correct_answer', 'N/A')}")
                
                elif question_type == 'true-false':
                    questions.append({
                        "number": idx,
                        "question": q_data.get("question", f"Question {idx}"),
                        "choices": {
                            "True": "True",
                            "False": "False"
                        }
                    })
                    answers.append(f"{idx}. {q_data.get('correct_answer', 'N/A')}")
                
                elif question_type == 'fill-blank':
                    questions.append({
                        "number": idx,
                        "question": q_data.get("question", f"Question {idx}"),
                        "choices": {}  # no choices for fill-in-the-blank
                    })
                    answers.append(f"{idx}. {q_data.get('correct_answer', 'N/A')}")

            sets.append({
                'set': f"Part {romanize(i)}",
                'difficulty': difficulty,
                'question_type': question_type,
                'questions': questions,
                'key_to_correction': answers
            })

        response = {
            'quiz': {
                'Number of Questions': sum(len(s['questions']) for s in sets),
                'Text from PDF (preview)': text[:500],
                'Generated Sets': sets
            }
        }

        return jsonify(response)

    except Exception as e:
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'PDF Quiz Generator API is running with Gemini'})

if __name__ == '__main__':
    app.run(debug=True)