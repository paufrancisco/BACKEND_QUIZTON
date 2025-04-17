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

@app.route('/convert', methods=['POST'])
def convert():
    file = request.files.get('files[]')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    pdf_reader = PyPDF2.PdfReader(file)
    text = ''.join([page.extract_text() for page in pdf_reader.pages])

    question_type = request.form.get('questionType')
    num_sets = int(request.form.get('numSets'))

    sets = []
    for i in range(1, num_sets + 1):
        set_questions = int(request.form.get(f'set-{i}-questions'))
        difficulty = request.form.get(f'set-{i}-difficulty')
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

            else:
                questions.append(f"{q}. Unsupported question type")
                answers.append(f"{q}. N/A")

        sets.append({
            'set': f"Set-{chr(64 + i)}",
            'difficulty': difficulty,
            'questions': questions,
            'key_to_correction': answers
        })

    response = {
        'quiz': {
            'Question Type': question_type,
            'Number of Questions': sum(len(s['questions']) for s in sets),
            'Text from PDF (preview)': text[:500],
            'Generated Sets': sets
        }
    }

    return jsonify(response)

if __name__ == '__main__':
    app.run(debug=True)
