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

# ✅ Simplified CORS config (supports Netlify + Vercel + local dev)
CORS(
    app,
    resources={r"/*": {"origins": [
        "http://127.0.0.1:5500",
        "https://paufrancisco.github.io",
        "https://quizton-lake.vercel.app",
        "https://sample-render-hosting-1.onrender.com",
        r"https://.*\.netlify\.app",   # allow all Netlify previews
        r"https://.*\.vercel\.app"     # allow all Vercel previews
    ]}},
    supports_credentials=True
)

# ✅ Initialize Gemini client
api_key = os.getenv("GEMINI_API_KEY")
model = None
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        print("Gemini client initialized ✅")
    except Exception as e:
        print(f"Error initializing Gemini: {e}")
else:
    print("⚠️ GEMINI_API_KEY not found in environment variables")

# Utility
def romanize(num):
    roman_numerals = ['I', 'II', 'III']
    return roman_numerals[num - 1] if 1 <= num <= 3 else str(num)

# Question generation
def generate_questions_with_gemini(text, question_type, difficulty, num_questions):
    if not model:
        return generate_fallback_questions(question_type, num_questions)

    if question_type == 'multiple-choice':
        prompt = f"""
        Based on the following text, generate {num_questions} multiple-choice questions with difficulty level: {difficulty}.
        Text: {text[:3000]}
        Requirements:
        - {num_questions} questions only
        - Difficulty: {difficulty}
        - Each question has 4 choices (A–D) and a correct answer
        Format strictly as JSON array:
        [{{"question": "...","choices": {{"A":"...","B":"...","C":"...","D":"..."}},"correct_answer":"A"}}]
        """
    elif question_type == 'true-false':
        prompt = f"""
        Based on the following text, generate {num_questions} true/false questions with difficulty {difficulty}.
        Text: {text[:3000]}
        Requirements:
        - {num_questions} questions only
        - Each with a statement + correct answer (True/False)
        Format strictly as JSON array:
        [{{"question": "...","correct_answer":"True"}}]
        """
    else:  # fill-blank
        prompt = f"""
        Based on the following text, generate {num_questions} fill-in-the-blank questions with difficulty {difficulty}.
        Text: {text[:3000]}
        Requirements:
        - {num_questions} questions only
        - Use ____ for blanks
        Format strictly as JSON array:
        [{{"question": "The ____ ...","correct_answer":"..."}}]
        """

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(response_text)
    except Exception as e:
        print(f"Gemini error: {e}")
        return generate_fallback_questions(question_type, num_questions)

def generate_fallback_questions(question_type, num_questions):
    questions = []
    for i in range(1, num_questions + 1):
        if question_type == 'multiple-choice':
            questions.append({
                "question": f"Sample MCQ {i} (fallback)",
                "choices": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                "correct_answer": random.choice(["A", "B", "C", "D"])
            })
        elif question_type == 'true-false':
            questions.append({
                "question": f"Sample True/False {i} (fallback)",
                "correct_answer": random.choice(["True", "False"])
            })
        else:
            questions.append({
                "question": f"Fill in the blank {i}: ____ (fallback)",
                "correct_answer": f"Answer{i}"
            })
    return questions

# Routes
@app.route('/convert', methods=['POST'])
def convert():
    file = request.files.get('files[]')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = ''.join([page.extract_text() or '' for page in pdf_reader.pages])

        if not text.strip():
            return jsonify({'error': 'No text could be extracted from PDF'}), 400

        num_sets = min(int(request.form.get('numSets', 1)), 3)
        sets = []

        for i in range(1, num_sets + 1):
            set_questions = int(request.form.get(f'set-{i}-questions', 5))
            difficulty = request.form.get(f'set-{i}-difficulty', 'easy')
            question_type = request.form.get(f'set-{i}-question-type', 'multiple-choice')

            generated_questions = generate_questions_with_gemini(text, question_type, difficulty, set_questions)

            questions, answers = [], []
            for idx, q in enumerate(generated_questions[:set_questions], 1):
                if question_type == 'multiple-choice':
                    questions.append({"number": idx, "question": q["question"], "choices": q["choices"]})
                    answers.append(f"{idx}. {q['correct_answer']}")
                elif question_type == 'true-false':
                    questions.append({"number": idx, "question": q["question"], "choices": {"True": "True", "False": "False"}})
                    answers.append(f"{idx}. {q['correct_answer']}")
                else:
                    questions.append({"number": idx, "question": q["question"], "choices": {}})
                    answers.append(f"{idx}. {q['correct_answer']}")

            sets.append({
                "set": f"Part {romanize(i)}",
                "difficulty": difficulty,
                "question_type": question_type,
                "questions": questions,
                "key_to_correction": answers
            })

        return jsonify({
            "quiz": {
                "Number of Questions": sum(len(s["questions"]) for s in sets),
                "Text from PDF (preview)": text[:500],
                "Generated Sets": sets
            }
        })
    except Exception as e:
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'message': 'PDF Quiz Generator API running'})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
