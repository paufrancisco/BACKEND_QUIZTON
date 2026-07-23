from flask import Flask, request, jsonify
from flask_cors import CORS
import PyPDF2
import random
import google.generativeai as genai
import json
from dotenv import load_dotenv
import os

###### Load environment variables ######
load_dotenv()
app = Flask(__name__)
###### Load environment variables ######


#############################################################################
######## Simplified CORS config (supports Netlify + Vercel + local dev)######
#############################################################################
CORS(
    app,
    resources={r"/*": {"origins": [
        "http://127.0.0.1:5500",
        "https://paufrancisco.github.io",
        "https://quizton-lake.vercel.app",
        "https://sample-render-hosting-1.onrender.com",
        r"https://.*\.netlify\.app",
        r"https://.*\.vercel\.app"
    ]}},
    supports_credentials=True
)
#############################################################################
######## Simplified CORS config (supports Netlify + Vercel + local dev)######
#############################################################################


#############################################################################
################### Config: tune these if you still see timeouts ###########
#############################################################################
GEMINI_REQUEST_TIMEOUT = 60      # seconds, per Gemini API call (currently unused - see note below)
MAX_PROMPT_CHARS = 10000         # was 30000 - smaller prompt = faster response
PAGE_SAMPLE_CHARS = 500          # was 800 - trimmed per-page sample size
#############################################################################


#############################################################################
################### Initialize Gemini client ################################
#############################################################################

api_key = os.getenv("GEMINI_API_KEY")
backup_api_key = os.getenv("GEMINI_API_KEY2")
model = None

# Try backup key FIRST for testing
if backup_api_key:
    try:
        genai.configure(api_key=backup_api_key)
        model = genai.GenerativeModel('gemini-3.5-flash')
        print("Gemini client initialized with backup key (GEMINI_API_KEY2) ✅")
    except Exception as e:
        print(f"Error with backup key: {e}")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-3.5-flash')
                print("Gemini client initialized with primary key ✅")
            except Exception as e2:
                print(f"Error with primary key: {e2}")
        else:
            print("⚠️ No primary key available")
elif api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-3.5-flash')
        print("Gemini client initialized with primary key ✅")
    except Exception as e:
        print(f"Error initializing Gemini with primary key: {e}")
else:
    print("⚠️ No GEMINI_API_KEY or GEMINI_API_KEY2 found in environment variables")
#############################################################################
################### Initialize Gemini client ################################
#############################################################################



#############################################################################
########################### UTILITY ########################################
#############################################################################
def romanize(num):
    roman_numerals = ['I', 'II', 'III']
    return roman_numerals[num - 1] if 1 <= num <= 3 else str(num)


def simple_rephrase_fallback(question: str) -> str:
    """Simple rule-based rephrasing when Gemini model isn't available"""

    # Dictionary of simple word replacements
    replacements = {
        'What is': 'What does',
        'What are': 'What do',
        'How is': 'How does',
        'How are': 'How do',
        'Why is': 'Why does',
        'Why are': 'Why do',
        'When is': 'When does',
        'When are': 'When do',
        'Where is': 'Where does',
        'Where are': 'Where do',
        'Which is': 'Which would be',
        'define': 'explain',
        'explain': 'describe',
        'describe': 'define'
    }

    # Apply simple transformations
    rephrased = question

    # Try word replacements
    for old, new in replacements.items():
        if old in rephrased:
            rephrased = rephrased.replace(old, new, 1)
            break

    # If no changes made, add variation
    if rephrased == question:
        if question.endswith('?'):
            rephrased = f"Can you explain: {question[:-1]}?"
        else:
            rephrased = f"Please clarify: {question}"

    return rephrased


def extract_text_with_pages(pdf_reader):
    """Extract text from PDF and track which page each section came from"""
    pages_data = []
    for page_num, page in enumerate(pdf_reader.pages, 1):
        text = page.extract_text() or ''
        if text.strip():
            pages_data.append({
                'page_number': page_num,
                'text': text.strip()
            })
    return pages_data


def find_source_page(source_text, pages_data):
    """Find which page the source content came from - EXACT PHRASE MATCHING"""
    if not source_text or not pages_data:
        return 1

    # Normalize text
    source_lower = source_text.lower().strip()

    # Try to find exact phrase match
    for page_data in pages_data:
        page_text_lower = page_data['text'].lower()

        # Take first 30 characters and last 30 characters of source
        if len(source_lower) > 60:
            first_part = source_lower[:30]
            last_part = source_lower[-30:]

            # If both parts appear in the page, it's likely the right page
            if first_part in page_text_lower and last_part in page_text_lower:
                print(f"✅ Exact match found on page {page_data['page_number']}")
                return page_data['page_number']
        else:
            # For shorter sources, check if most of it appears
            if source_lower in page_text_lower:
                print(f"✅ Exact match found on page {page_data['page_number']}")
                return page_data['page_number']

    # Fallback: word-based matching
    import re
    source_words = re.findall(r'\b\w{4,}\b', source_lower)  # Words with 4+ chars

    if source_words:
        best_page = 1
        best_count = 0

        for page_data in pages_data:
            page_text_lower = page_data['text'].lower()
            count = sum(1 for word in source_words if word in page_text_lower)

            if count > best_count:
                best_count = count
                best_page = page_data['page_number']

        match_ratio = best_count / len(source_words) if source_words else 0
        if match_ratio > 0.3:  # If at least 30% of words match
            print(f"📄 Best match on page {best_page} ({match_ratio*100:.1f}% words matched)")
            return best_page

    print(f"⚠️ No good match found, defaulting to page 1")
    return 1
#############################################################################
########################### UTILITY ########################################
#############################################################################




######################################################################################################################################
####################################### Question generation ##########################################################################
######################################################################################################################################


def generate_questions_with_gemini(text, question_type, difficulty, num_questions, pages_data=None):
    """Generate questions with source content tracking - IMPROVED TO USE FULL PDF"""
    if not model:
        return generate_fallback_questions(question_type, num_questions)

    # Trimmed from 30000 -> MAX_PROMPT_CHARS to reduce latency/memory and
    # avoid gunicorn worker timeouts on large PDFs
    text_chunk = text[:MAX_PROMPT_CHARS]

    # If we have multiple pages, include text from different pages
    page_samples = ""
    if pages_data and len(pages_data) > 1:
        # Sample from beginning, middle, and end pages
        sample_pages = []
        if len(pages_data) >= 3:
            sample_pages = [pages_data[0], pages_data[len(pages_data)//2], pages_data[-1]]
        else:
            sample_pages = pages_data

        page_samples = "\n\n--- PAGE SAMPLES ---\n"
        for page in sample_pages:
            page_samples += f"\n[Page {page['page_number']}]:\n{page['text'][:PAGE_SAMPLE_CHARS]}\n"

    if question_type == 'multiple-choice':
        prompt = f"""
        Based on the following text from a multi-page document, generate {num_questions} multiple-choice questions with difficulty level: {difficulty}.

        IMPORTANT: Create questions from DIFFERENT parts of the document, not just the beginning.

        Text excerpt:
        {text_chunk}

        {page_samples}

        Requirements:
        - Generate EXACTLY {num_questions} questions
        - Difficulty: {difficulty}
        - Each question has 4 choices (A–D) and a correct answer
        - CRITICAL: Include "source_content" field with the EXACT 2-3 sentence excerpt from the text that the question is based on
        - Spread questions across different sections of the document

        Format strictly as JSON array:
        [{{
            "question": "...",
            "choices": {{"A":"...","B":"...","C":"...","D":"..."}},
            "correct_answer":"A",
            "source_content": "The exact 2-3 sentences from the text that this question is based on"
        }}]
        """
    elif question_type == 'true-false':
        prompt = f"""
        Based on the following text from a multi-page document, generate {num_questions} true/false questions with difficulty {difficulty}.

        IMPORTANT: Create questions from DIFFERENT parts of the document, not just the beginning.

        Text excerpt:
        {text_chunk}

        {page_samples}

        Requirements:
        - Generate EXACTLY {num_questions} questions
        - Each with a statement + correct answer (True/False)
        - CRITICAL: Include "source_content" field with the EXACT 2-3 sentence excerpt from the text
        - Spread questions across different sections of the document

        Format strictly as JSON array:
        [{{
            "question": "...",
            "correct_answer":"True",
            "source_content": "The exact 2-3 sentences from the text that this question is based on"
        }}]
        """
    else:  # fill-blank
        prompt = f"""
        Based on the following text from a multi-page document, generate {num_questions} fill-in-the-blank questions with difficulty {difficulty}.

        IMPORTANT: Create questions from DIFFERENT parts of the document, not just the beginning.

        Text excerpt:
        {text_chunk}

        {page_samples}

        Requirements:
        - Generate EXACTLY {num_questions} questions
        - Use ____ for blanks
        - Provide the correct answer for each blank
        - CRITICAL: Include "source_content" field with the EXACT 2-3 sentence excerpt from the text
        - Spread questions across different sections of the document

        Format strictly as JSON array:
        [{{
            "question": "The ____ ...",
            "correct_answer": "the correct word or phrase",
            "source_content": "The exact 2-3 sentences from the text that this question is based on"
        }}]
        """

    try:
        # NOTE: request_options={"timeout": ...} was removed here because the
        # installed google-generativeai version no longer accepts it as a
        # valid kwarg on generate_content() - it was being forwarded into
        # GenerateContentRequest which has no such field, causing every
        # call to fail and silently fall back to generate_fallback_questions().
        response = model.generate_content(prompt)
        response_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        questions = json.loads(response_text)

        # Add source page information
        if pages_data:
            print(f"\n📚 Matching questions to {len(pages_data)} pages...")
            for idx, q in enumerate(questions, 1):
                source_content = q.get('source_content', '')
                if source_content and len(source_content) > 10:
                    page_num = find_source_page(source_content, pages_data)
                    q['source_page'] = page_num
                    print(f"  Q{idx}: Matched to page {page_num}")
                else:
                    q['source_content'] = 'Source content not provided by AI'
                    q['source_page'] = 1
                    print(f"  Q{idx}: No source content provided")
        else:
            for q in questions:
                if 'source_content' not in q:
                    q['source_content'] = 'Source tracking not available'
                if 'source_page' not in q:
                    q['source_page'] = 1

        return questions
    except Exception as e:
        print(f"Gemini error: {e}")
        import traceback
        traceback.print_exc()
        return generate_fallback_questions(question_type, num_questions)


def rephrase_question_with_gemini(question, difficulty="medium", question_type="multiple-choice"):
    """Rephrase a question using Gemini AI"""
    if not model:
        print("Gemini model not available, using fallback")
        return simple_rephrase_fallback(question)

    try:
        prompt = f"""
        Rephrase the following question while maintaining its meaning and difficulty level ({difficulty}).

        Original question: {question}
        Question type: {question_type}
        Difficulty: {difficulty}

        Requirements:
        - Keep the same meaning and answer
        - Maintain {difficulty} difficulty level
        - Use different wording/structure
        - If it's a {question_type} question, keep the same format
        - Return only the rephrased question, nothing else

        Rephrased question:
        """

        # request_options removed - see note in generate_questions_with_gemini
        response = model.generate_content(prompt)
        rephrased = response.text.strip()

        if rephrased.startswith('"') and rephrased.endswith('"'):
            rephrased = rephrased[1:-1]

        if question.endswith('?') and not rephrased.endswith('?'):
            rephrased += '?'
        elif question.endswith(':') and not rephrased.endswith(':'):
            rephrased += ':'

        return rephrased if rephrased != question else simple_rephrase_fallback(question)

    except Exception as e:
        print(f"Gemini rephrase error: {e}, using fallback")
        return simple_rephrase_fallback(question)


def regenerate_question_with_gemini(original_question, context="", difficulty="medium", question_type="multiple-choice"):
    """Regenerate a completely new question using Gemini AI"""
    if not model:
        return generate_fallback_single_question(question_type, difficulty)

    try:
        if question_type == 'multiple-choice':
            prompt = f"""
            Generate a new multiple-choice question different from the original but with similar difficulty.

            Original question: {original_question}
            Context/Topic: {context if context else "Based on the original question's topic"}
            Difficulty: {difficulty}

            Requirements:
            - Create a completely different question on a similar topic
            - Difficulty level: {difficulty}
            - Format as JSON: {{"question": "...","choices": {{"A":"...","B":"...","C":"...","D":"..."}},"correct_answer":"A"}}
            - Return only valid JSON, nothing else
            """
        elif question_type == 'true-false':
            prompt = f"""
            Generate a new true/false question different from the original but with similar difficulty.

            Original question: {original_question}
            Context/Topic: {context if context else "Based on the original question's topic"}
            Difficulty: {difficulty}

            Requirements:
            - Create a completely different question on a similar topic
            - Difficulty level: {difficulty}
            - Format as JSON: {{"question": "...","correct_answer":"True"}}
            - Return only valid JSON, nothing else
            """
        else:  # fill-blank
            prompt = f"""
            Generate a new fill-in-the-blank question different from the original but with similar difficulty.

            Original question: {original_question}
            Context/Topic: {context if context else "Based on the original question's topic"}
            Difficulty: {difficulty}

            Requirements:
            - Create a completely different question on a similar topic
            - Use ____ for blanks
            - Difficulty level: {difficulty}
            - Format as JSON: {{"question": "...","correct_answer":"..."}}
            - Return only valid JSON, nothing else
            """

        # request_options removed - see note in generate_questions_with_gemini
        response = model.generate_content(prompt)
        response_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()

        return json.loads(response_text)

    except Exception as e:
        print(f"Gemini regenerate error: {e}, using fallback")
        return generate_fallback_single_question(question_type, difficulty)


def generate_fallback_single_question(question_type, difficulty):
    """Generate a single fallback question"""
    if question_type == 'multiple-choice':
        return {
            "question": f"Sample {difficulty} MCQ (regenerated)",
            "choices": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
            "correct_answer": "A"
        }
    elif question_type == 'true-false':
        return {
            "question": f"Sample {difficulty} True/False statement (regenerated)",
            "correct_answer": "True"
        }
    else:
        return {
            "question": f"Fill the {difficulty} blank: The ____ is important (regenerated)",
            "correct_answer": "answer"
        }

######################################################################################################################################
####################################### Question generation ##########################################################################
######################################################################################################################################





#####################################################################################################
#################### Generate Fallback Questions  ###################################################
#####################################################################################################
def generate_fallback_questions(question_type, num_questions):
    """Generate fallback questions with source content"""
    questions = []
    for i in range(1, num_questions + 1):
        if question_type == 'multiple-choice':
            questions.append({
                "question": f"Sample MCQ {i} (fallback mode - Gemini unavailable)",
                "choices": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                "correct_answer": random.choice(["A", "B", "C", "D"]),
                "source_content": "This is a fallback question generated when AI is unavailable. Source tracking requires Gemini AI.",
                "source_page": 1
            })
        elif question_type == 'true-false':
            questions.append({
                "question": f"Sample True/False {i} (fallback mode - Gemini unavailable)",
                "correct_answer": random.choice(["True", "False"]),
                "source_content": "This is a fallback question generated when AI is unavailable. Source tracking requires Gemini AI.",
                "source_page": 1
            })
        else:
            questions.append({
                "question": f"Fill in the blank {i}: The ____ is important (fallback mode)",
                "correct_answer": f"Answer{i}",
                "source_content": "This is a fallback question generated when AI is unavailable. Source tracking requires Gemini AI.",
                "source_page": 1
            })
    return questions
#####################################################################################################
#################### Generate Fallback Questions  ###################################################
#####################################################################################################



###############################################################################################################################
############################## Routes POST ####################################################################################
###############################################################################################################################
@app.route('/convert', methods=['POST'])
def convert():
    file = request.files.get('files[]')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    try:
        pdf_reader = PyPDF2.PdfReader(file)

        # Extract text with page tracking
        pages_data = extract_text_with_pages(pdf_reader)
        text = ' '.join([page['text'] for page in pages_data])

        if not text.strip():
            return jsonify({'error': 'No text could be extracted from PDF'}), 400

        num_sets = min(int(request.form.get('numSets', 1)), 3)
        sets = []

        for i in range(1, num_sets + 1):
            set_questions = int(request.form.get(f'set-{i}-questions', 5))
            difficulty = request.form.get(f'set-{i}-difficulty', 'easy')
            question_type = request.form.get(f'set-{i}-question-type', 'multiple-choice')

            # Generate questions with source tracking
            generated_questions = generate_questions_with_gemini(
                text, question_type, difficulty, set_questions, pages_data
            )

            questions, answers = [], []
            for idx, q in enumerate(generated_questions[:set_questions], 1):
                question_data = {
                    "number": idx,
                    "question": q["question"],
                    "source_content": q.get("source_content", "Source content not available"),
                    "source_page": q.get("source_page", 1)
                }

                if question_type == 'multiple-choice':
                    question_data["choices"] = q["choices"]
                    answers.append(f"{idx}. {q['correct_answer']}")
                elif question_type == 'true-false':
                    question_data["choices"] = {"True": "True", "False": "False"}
                    answers.append(f"{idx}. {q['correct_answer']}")
                else:
                    question_data["choices"] = {}
                    answers.append(f"{idx}. {q['correct_answer']}")

                questions.append(question_data)

            sets.append({
                "set": f"Part {romanize(i)}",
                "difficulty": difficulty,
                "question_type": question_type,
                "questions": questions,
                "key_to_correction": answers,
                "numberOfQuestions": len(questions)
            })

        return jsonify({
            "quiz": {
                "Number of Questions": sum(len(s["questions"]) for s in sets),
                "Text from PDF (preview)": text[:500],
                "Generated Sets": sets
            }
        })
    except Exception as e:
        print(f"Error in /convert: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500


@app.route('/rephrase', methods=['POST'])
def rephrase():
    """Handle question rephrasing and regeneration using Gemini"""
    try:
        data = request.json
        action = data.get("action")
        question = data.get("question", "")
        answer = data.get("answer", "")
        choices = data.get("choices", [])
        difficulty = data.get("difficulty", "medium").lower()
        q_type = data.get("question_type", "multiple-choice").lower()
        context = data.get("context", "")

        print(f"Processing {action} for: {question}")

        if not question:
            return jsonify({"error": "No question provided"}), 400

        if action == "rephrase":
            try:
                new_question = rephrase_question_with_gemini(question, difficulty, q_type)
                print(f"Original: {question}")
                print(f"Rephrased: {new_question}")

                return jsonify({
                    "question": new_question,
                    "answer": answer,
                    "choices": choices
                })

            except Exception as e:
                print(f"Rephrase error: {e}")
                return jsonify({"error": f"Rephrasing failed: {str(e)}"}), 500

        elif action == "regenerate":
            try:
                regenerated = regenerate_question_with_gemini(question, context, difficulty, q_type)

                if regenerated:
                    response_data = {
                        "question": regenerated["question"],
                        "answer": regenerated.get("correct_answer", regenerated.get("answer", ""))
                    }

                    if "choices" in regenerated and regenerated["choices"]:
                        choices_data = regenerated["choices"]
                        if isinstance(choices_data, dict):
                            response_data["choices"] = [f"{k}. {v}" for k, v in choices_data.items()]
                        else:
                            response_data["choices"] = choices_data

                    return jsonify(response_data)
                else:
                    return jsonify({"error": "Could not regenerate this question"}), 400

            except Exception as e:
                print(f"Regenerate error: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({"error": f"Regeneration failed: {str(e)}"}), 500

        else:
            return jsonify({"error": "Invalid action. Use 'rephrase' or 'regenerate'"}), 400

    except Exception as e:
        print(f"Route error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Server error: {str(e)}"}), 500
###############################################################################################################################
############################## Routes POST ####################################################################################
###############################################################################################################################




#############################################################################
############################## Routes GET ###################################
#############################################################################
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'message': 'PDF Quiz Generator API running'})


@app.route('/test-rephrase', methods=['GET'])
def test_rephrase():
    """Test the rephrase function"""
    test_question = "What is the capital of France?"
    try:
        rephrased = rephrase_question_with_gemini(test_question, "medium", "multiple-choice")
        return jsonify({
            "original": test_question,
            "rephrased": rephrased,
            "status": "success",
            "gemini_available": model is not None
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "failed"
        }), 500


@app.route('/test-regenerate', methods=['GET'])
def test_regenerate():
    """Test the regenerate function"""
    test_question = "What is the capital of France?"
    try:
        regenerated = regenerate_question_with_gemini(test_question, "", "medium", "multiple-choice")
        return jsonify({
            "original": test_question,
            "regenerated": regenerated,
            "status": "success",
            "gemini_available": model is not None
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "failed"
        }), 500
#############################################################################
############################## Routes GET ###################################
#############################################################################






#############################################################################
############################  RUN MAIN ######################################
#############################################################################

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
#############################################################################
############################  RUN MAIN ######################################
#############################################################################