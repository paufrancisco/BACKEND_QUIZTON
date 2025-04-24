from flask import Flask, request, jsonify
from flask_cors import CORS
import PyPDF2
import random

app = Flask(__name__)
CORS(app, origins=[
    "http://127.0.0.1:5500",
    "https://sample-render-hosting-1.onrender.com",
    "https://paufrancisco.github.io"
])

def romanize(num):
    roman_numerals = ['I', 'II', 'III']
    return roman_numerals[num - 1] if 1 <= num <= 3 else str(num)

@app.route('/convert', methods=['POST'])
def convert():
    file = request.files.get('files[]')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    pdf_reader = PyPDF2.PdfReader(file)
    text = ''.join([page.extract_text() or '' for page in pdf_reader.pages])

    num_sets = int(request.form.get('numSets'))
    num_sets = min(num_sets, 3)  # Limit to a max of 3 parts

    sets = []

    for i in range(1, num_sets + 1):
        set_questions = int(request.form.get(f'set-{i}-questions'))
        difficulty = request.form.get(f'set-{i}-difficulty')
        question_type = request.form.get(f'set-{i}-question-type')

        questions, answers = [], []

        for q in range(1, set_questions + 1):
            if question_type == 'multiple-choice':
                question = f"{q}. Sample Question {q} (Difficulty: {difficulty})"
                choices = {
                    "A": f"A. Choice A for Question {q}",
                    "B": f"B. Choice B for Question {q}",
                    "C": f"C. Choice C for Question {q}",
                    "D": f"D. Choice D for Question {q}"
                }
                correct_answer = random.choice(['A', 'B', 'C', 'D'])
                question_text = question + "\n" + "\n".join(choices.values())
                questions.append(question_text)
                answers.append(f"{q}. {correct_answer}")
            elif question_type == 'true-false':
                question = f"{q}. Sample True/False Question {q} (Difficulty: {difficulty})"
                correct_answer = random.choice(['True', 'False'])
                questions.append(question)
                answers.append(f"{q}. {correct_answer}")
            elif question_type == 'fill-blank':
                question = f"{q}. Fill in the blank: _____ is part of Part {romanize(i)} (Difficulty: {difficulty})"
                correct_answer = f"Answer{q}"
                questions.append(question)
                answers.append(f"{q}. {correct_answer}")
            else:
                questions.append(f"{q}. Unsupported question type")
                answers.append(f"{q}. N/A")

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

if __name__ == '__main__':
    app.run(debug=True)
