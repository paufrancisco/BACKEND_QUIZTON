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
################### Initialize Gemini client ################################
#############################################################################

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
#############################################################################
################### Initialize Gemini client ################################
#############################################################################
    


#############################################################################
########################### UTITLITY ########################################
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
            rephrased = rephrased.replace(old, new, 1)  # Replace only first occurrence
            break
    
    # If no changes made, add variation
    if rephrased == question:
        if question.endswith('?'):
            rephrased = f"Can you explain: {question[:-1]}?"
        else:
            rephrased = f"Please clarify: {question}"
    
    return rephrased
#############################################################################
########################### UTITLITY ########################################
#############################################################################





######################################################################################################################################
####################################### Question generation ##########################################################################
######################################################################################################################################
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
        - Provide the correct answer for each blank in the "correct_answer" field
        Format strictly as JSON array:
        [
        {{
            "question": "The ____ ...",
            "correct_answer": "the correct word or phrase that fills the blank"
        }}
        ]
        """

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(response_text)
    except Exception as e:
        print(f"Gemini error: {e}")
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




###############################################################################################################################
############################## REPHRASE POST ##################################################################################
###############################################################################################################################
@app.route('/rephrase', methods=['POST'])
def rephrase_question():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        action = data.get('action')  # 'rephrase' or 'regenerate'
        current_question = data.get('question')
        question_type = data.get('question_type', 'multiple-choice')
        difficulty = data.get('difficulty', 'medium')
        current_choices = data.get('current_choices', {})
        current_correct_answer = data.get('current_correct_answer', '')
        
        if not action or not current_question:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Use Gemini to rephrase or regenerate
        if model:
            if action == 'rephrase':
                result = rephrase_with_gemini(current_question, question_type, difficulty, current_choices, current_correct_answer)
            else:  # regenerate
                result = regenerate_with_gemini(question_type, difficulty)
        else:
            # Fallback if Gemini is not available
            result = generate_fallback_rephrase(action, current_question, question_type, current_choices, current_correct_answer)
        
        return jsonify({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        print(f"Error in rephrase endpoint: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
###############################################################################################################################
############################## REPHRASE POST ##################################################################################
###############################################################################################################################




###############################################################################################################################
############################## REPHRASE with GEMINI ###########################################################################
###############################################################################################################################


def rephrase_with_gemini(question, question_type, difficulty, current_choices, current_answer):
    """Rephrase question while keeping the same answer"""
    try:
        if question_type == 'multiple-choice':
            prompt = f"""
            Rephrase the following multiple-choice question while keeping the same correct answer and concept.
            The difficulty should remain: {difficulty}
            
            Original question: {question}
            Current choices: {current_choices}
            Correct answer: {current_answer}
            
            Requirements:
            - Keep the same correct answer ({current_answer})
            - Keep the same concept but rephrase the question differently
            - Maintain difficulty level: {difficulty}
            - Provide 4 choices (A-D)
            
            Format as JSON:
            {{
                "question": "rephrased question text",
                "choices": {{"A": "choice A", "B": "choice B", "C": "choice C", "D": "choice D"}},
                "correct_answer": "{current_answer}"
            }}
            """
        elif question_type == 'true-false':
            prompt = f"""
            Rephrase the following true/false question while keeping the same correct answer.
            The difficulty should remain: {difficulty}
            
            Original question: {question}
            Correct answer: {current_answer}
            
            Requirements:
            - Keep the same correct answer ({current_answer})
            - Rephrase the statement differently but maintain the same truth value
            - Maintain difficulty level: {difficulty}
            
            Format as JSON:
            {{
                "question": "rephrased question text",
                "correct_answer": "{current_answer}"
            }}
            """
        else:  # fill-blank
            prompt = f"""
            Rephrase the following fill-in-the-blank question while keeping the same answer.
            The difficulty should remain: {difficulty}
            
            Original question: {question}
            Correct answer: {current_answer}
            
            Requirements:
            - Keep the same answer ({current_answer})
            - Rephrase the question sentence differently but use ____ for the blank
            - The blank should still be answered by: {current_answer}
            - Maintain difficulty level: {difficulty}
            
            Format as JSON:
            {{
                "question": "rephrased question with ____",
                "correct_answer": "{current_answer}"
            }}
            """
        
        response = model.generate_content(prompt)
        response_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(response_text)
        
    except Exception as e:
        print(f"Gemini rephrase error: {e}")
        return generate_fallback_rephrase('rephrase', question, question_type, current_choices, current_answer)

###############################################################################################################################
############################## REPHRASE with GEMINI ###########################################################################
###############################################################################################################################



###############################################################################################################################
############################## REGENERATE with GEMINI #########################################################################
###############################################################################################################################


def regenerate_with_gemini(question_type, difficulty):
    """Generate completely new question and answer"""
    try:
        if question_type == 'multiple-choice':
            prompt = f"""
            Generate a new multiple-choice question with difficulty: {difficulty}.
            
            Requirements:
            - Completely new question (not related to any previous content)
            - 4 choices (A-D) with one correct answer
            - Difficulty: {difficulty}
            - Make it educational and meaningful
            
            Format as JSON:
            {{
                "question": "new question text",
                "choices": {{"A": "choice A", "B": "choice B", "C": "choice C", "D": "choice D"}},
                "correct_answer": "A"
            }}
            """
        elif question_type == 'true-false':
            prompt = f"""
            Generate a new true/false question with difficulty: {difficulty}.
            
            Requirements:
            - Completely new statement
            - Difficulty: {difficulty}
            - Make it educational and meaningful
            
            Format as JSON:
            {{
                "question": "new statement",
                "correct_answer": "True"
            }}
            """
        else:  # fill-blank
            prompt = f"""
            Generate a new fill-in-the-blank question with difficulty: {difficulty}.
            
            Requirements:
            - Completely new question with ____
            - Difficulty: {difficulty}
            - Make it educational and meaningful
            
            Format as JSON:
            {{
                "question": "new question with ____",
                "correct_answer": "answer for the blank"
            }}
            """
        
        response = model.generate_content(prompt)
        response_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(response_text)
        
    except Exception as e:
        print(f"Gemini regenerate error: {e}")
        return generate_fallback_rephrase('regenerate', '', question_type, {}, '')


###############################################################################################################################
############################## REGENERATE with GEMINI #########################################################################
###############################################################################################################################




###############################################################################################################################
############################## FALLBACK REPHRASE  #############################################################################
###############################################################################################################################



def generate_fallback_rephrase(action, question, question_type, current_choices, current_answer):
    """Fallback function when Gemini is not available"""
    if action == 'rephrase':
        if question_type == 'multiple-choice':
            return {
                "question": f"Rephrased: {question}",
                "choices": current_choices,
                "correct_answer": current_answer
            }
        elif question_type == 'true-false':
            return {
                "question": f"Rephrased: {question}",
                "correct_answer": current_answer
            }
        else:  # fill-blank
            return {
                "question": question.replace('____', '______'),
                "correct_answer": current_answer
            }
    else:  # regenerate
        fallback_questions = {
            'multiple-choice': {
                "question": "What is 2 + 2?",
                "choices": {"A": "3", "B": "4", "C": "5", "D": "6"},
                "correct_answer": "B"
            },
            'true-false': {
                "question": "The sun rises in the east.",
                "correct_answer": "True"
            },
            'fill-blank': {
                "question": "The capital of France is ____.",
                "correct_answer": "Paris"
            }
        }
        return fallback_questions.get(question_type, fallback_questions['multiple-choice'])

###############################################################################################################################
############################## FALLBACK REPHRASE  #############################################################################
###############################################################################################################################





#############################################################################
############################  RUN MAIN ######################################
#############################################################################

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
#############################################################################
############################  RUN MAIN ######################################
#############################################################################