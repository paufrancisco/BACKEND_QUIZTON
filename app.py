from flask import Flask, request, jsonify
from flask_cors import CORS
import PyPDF2

app = Flask(__name__)

# Enable CORS for specific origins
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
    text = ''
    for page in pdf_reader.pages:
        text += page.extract_text()

    question_type = request.form.get('questionType')
    difficulty = request.form.get('difficulty')
    num_sets = int(request.form.get('numSets'))

    sets = []
    for i in range(1, num_sets + 1):
        set_questions = int(request.form.get(f'set-{i}'))
        questions = []

        for q in range(1, set_questions + 1):
            if question_type == 'multiple-choice':
                question = f"Sample Question {q} (Difficulty: {difficulty})"
                choices = {
                    "A": f"Choice A for Question {q}",
                    "B": f"Choice B for Question {q}",
                    "C": f"Choice C for Question {q}",
                    "D": f"Choice D for Question {q}"
                }
                correct_answer = "A"
                questions.append({
                    "question": question,
                    "choices": choices,
                    "answer": correct_answer
                })

            elif question_type == 'true-false':
                statement = f"Sample Statement {q} (Difficulty: {difficulty})"
                answer = "True" if q % 2 == 0 else "False"
                questions.append({
                    "statement": statement,
                    "answer": answer
                })

            elif question_type == 'fill-blank':
                sentence = f"The Earth is _____. (Difficulty: {difficulty})"
                correct_word = "round"
                questions.append({
                    "sentence": sentence,
                    "answer": correct_word
                })

            else:
                questions.append({
                    "error": "Invalid question type"
                })

        sets.append({
            'set': f'Set-{chr(64 + i)}',
            'questions': questions
        })

    response = {
        'quiz': {
            'Sets': sets,
            'Difficulty': difficulty,
            'Question Type': question_type,
            'Text from PDF': text[:500],
            'Number of Questions': sum(len(set['questions']) for set in sets)
        }
    }

    return jsonify(response)

if __name__ == '__main__':
    app.run(debug=True)
