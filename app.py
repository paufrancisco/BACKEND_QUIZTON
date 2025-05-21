from flask import Flask, request, jsonify
from flask_cors import CORS
import PyPDF2
import random
import spacy
from transformers import T5ForConditionalGeneration, T5Tokenizer

app = Flask(__name__)
CORS(app, origins=[
    "http://127.0.0.1:5500",
    "https://sample-render-hosting-1.onrender.com",
    "https://paufrancisco.github.io"
])

nlp = spacy.load("en_core_web_sm")
tokenizer = T5Tokenizer.from_pretrained("valhalla/t5-small-qa-qg-hl")
model = T5ForConditionalGeneration.from_pretrained("valhalla/t5-small-qa-qg-hl")

def romanize(num):
    roman_numerals = ['I', 'II', 'III']
    return roman_numerals[num - 1] if 1 <= num <= 3 else str(num)

def generate_question(sentence, answer):
    highlighted = sentence.replace(answer, f"<hl> {answer} <hl>", 1)
    input_text = f"generate question: {highlighted}"
    inputs = tokenizer.encode(input_text, return_tensors="pt")
    outputs = model.generate(inputs, max_length=64, num_beams=4, early_stopping=True)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)

def generate_mcq(sentence):
    doc = nlp(sentence)
    for ent in doc.ents:
        if ent.label_ in ['PERSON', 'ORG', 'GPE', 'DATE', 'NORP']:
            question = generate_question(sentence, ent.text)
            incorrects = ["Donald Trump", "George Washington", "Joe Biden", "Abraham Lincoln", "New York", "2020"]
            incorrects = [i for i in incorrects if i != ent.text]
            random.shuffle(incorrects)
            choices = [ent.text] + incorrects[:3]
            random.shuffle(choices)

            choice_map = dict(zip(["A", "B", "C", "D"], choices))
            correct_letter = next(k for k, v in choice_map.items() if v == ent.text)

            return {
                "question": question,
                "choices": choice_map,
                "correct": correct_letter
            }
    return None

def generate_true_false(sentence):
    doc = nlp(sentence)
    entities = list(doc.ents)
    is_true = random.choice([True, False])
    modified_sentence = sentence
    correct_answer = "True"

    if not is_true and entities:
        ent = random.choice(entities)
        fake_replacements = {
            "Barack Obama": "Donald Trump",
            "United States": "Russia",
            "2020": "1999",
            "New York": "Paris"
        }
        replacement = random.choice(list(fake_replacements.values()))
        modified_sentence = sentence.replace(ent.text, replacement, 1)
        correct_answer = "False"

    return {
        "question": modified_sentence,
        "choices": {"True": "True", "False": "False"},
        "correct": correct_answer
    }

def generate_fill_blank(sentence):
    doc = nlp(sentence)
    for ent in doc.ents:
        if ent.label_ in ['PERSON', 'ORG', 'GPE', 'DATE', 'NORP']:
            question = sentence.replace(ent.text, "_____")
            return {
                "question": question,
                "choices": {},
                "correct": ent.text
            }
    return None

@app.route('/convert', methods=['POST'])
def convert():
    file = request.files.get('files[]')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    pdf_reader = PyPDF2.PdfReader(file)
    text = ''.join([page.extract_text() or '' for page in pdf_reader.pages])
    sentences = [s.strip() for s in text.split('.') if len(s.split()) > 4]

    num_sets = int(request.form.get('numSets'))
    num_sets = min(num_sets, 3)

    sets = []
    current_sentence = 0

    for i in range(1, num_sets + 1):
        set_questions = int(request.form.get(f'set-{i}-questions'))
        difficulty = request.form.get(f'set-{i}-difficulty')
        question_type = request.form.get(f'set-{i}-question-type')

        questions = []
        answers = []

        count = 0
        while count < set_questions and current_sentence < len(sentences):
            sentence = sentences[current_sentence]
            current_sentence += 1

            generated = None
            if question_type == 'multiple-choice':
                generated = generate_mcq(sentence)
            elif question_type == 'true-false':
                generated = generate_true_false(sentence)
            elif question_type == 'fill-blank':
                generated = generate_fill_blank(sentence)

            if generated:
                count += 1
                questions.append({
                    "number": count,
                    "question": generated["question"],
                    "choices": generated["choices"]
                })
                answers.append(f"{count}. {generated['correct']}")

        sets.append({
            'set': f"Part {romanize(i)}",
            'difficulty': difficulty,
            'question_type': question_type,
            'questions': questions,
            'key_to_correction': answers
        })

    return jsonify({
        'quiz': {
            'Number of Questions': sum(len(s['questions']) for s in sets),
            'Text from PDF (preview)': text[:500],
            'Generated Sets': sets
        }
    })

if __name__ == '__main__':
    import os
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(
        debug=debug_mode,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000))
    )

