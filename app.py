from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import PyPDF2
import io

app = Flask(__name__)

# Enable CORS for specific origins
CORS(app, origins=["http://127.0.0.1:5500", "https://sample-render-hosting-1.onrender.com", "https://paufrancisco.github.io"])

@app.route('/convert', methods=['POST'])
def convert():
    # Extract the uploaded file from the request
    file = request.files.get('files[]')
    
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400
    
    # Read the PDF file to extract text
    pdf_reader = PyPDF2.PdfReader(file)
    text = ''
    for page in pdf_reader.pages:
        text += page.extract_text()

    # Get quiz options from the form data
    question_type = request.form.get('questionType')
    difficulty = request.form.get('difficulty')
    num_sets = int(request.form.get('numSets'))
    
    sets = []
    for i in range(1, num_sets + 1):
        set_questions = int(request.form.get(f'set-{i}'))
        sets.append({
            'set': f'Set-{chr(64 + i)}',
            'questions': set_questions
        })
    
    # Prepare a response message that includes the extracted text and form data
    response = {
        'quiz': {
            'Sets': sets,
            'Difficulty': difficulty,
            'Question Type': question_type,
            'Text from PDF': text[:500],  # Returning the first 500 characters of the extracted text as a preview
            'Mode of Difficulty': f"The quiz has a difficulty level of {difficulty}.",
            'Number of Questions': f"The total number of questions across all sets is {sum([set['questions'] for set in sets])}."
        }
    }

    return jsonify(response)

if __name__ == '__main__':
    app.run(debug=True)
