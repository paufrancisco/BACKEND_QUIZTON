from flask import Flask, request, jsonify
from flask_cors import CORS
import PyPDF2
import random
import re
import spacy
from transformers import (
    T5ForConditionalGeneration, 
    T5Tokenizer,
    AutoTokenizer, 
    AutoModelForQuestionAnswering,
    pipeline
)
import torch

app = Flask(__name__)
CORS(app, origins=[
    "http://127.0.0.1:5500",
    "https://sample-render-hosting-1.onrender.com",
    "https://paufrancisco.github.io"
])

# Load models
nlp = spacy.load("en_core_web_sm")

# T5 for question generation
t5_tokenizer = T5Tokenizer.from_pretrained("valhalla/t5-small-qa-qg-hl")
t5_model = T5ForConditionalGeneration.from_pretrained("valhalla/t5-small-qa-qg-hl")

# RoBERTa for question answering
try:
    qa_pipeline = pipeline("question-answering", 
                          model="deepset/roberta-base-squad2",
                          tokenizer="deepset/roberta-base-squad2")
    print("RoBERTa model loaded successfully")
except Exception as e:
    print(f"Warning: RoBERTa model failed to load: {e}")
    qa_pipeline = None


def romanize(num):
    roman_numerals = ['I', 'II', 'III']
    return roman_numerals[num - 1] if 1 <= num <= 3 else str(num)


def advanced_text_cleaning(text):
    """Advanced text cleaning to handle PDF artifacts"""
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s.,!?;:()\-\'"]', ' ', text)
    text = re.sub(r'^\s*[•·▪▫◦‣⁃]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[a-zA-Z]\.\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[ivxlcdm]+\.\s*', '', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'\ba\.\s+[A-Z][^.]*\s+b\.\s+[A-Z][^.]*\s+c\..*?(?=\s[A-Z]|\.|$)', ' ', text)
    text = re.sub(r'[a-z]\.\s+[A-Z][^.]*(?=\s+[a-z]\.|$)', ' ', text)

    sentences = re.split(r'[.!?]+', text)
    valid_sentences = []

    for sentence in sentences:
        sentence = sentence.strip()
        words = sentence.split()
        if (len(words) >= 5 and
            not re.match(r'^[a-z]\.\s*', sentence) and
            not sentence.startswith('•') and
            len([w for w in words if len(w) > 2]) >= 3):
            valid_sentences.append(sentence)
    return valid_sentences


def extract_quality_entities(sentences):
    """Extract only high-quality, complete entities"""
    entity_pool = {}
    sent_entities = []
    MIN_ENTITY_LENGTH = 2
    MAX_ENTITY_LENGTH = 50

    for sent in sentences:
        doc = nlp(sent)
        ents_in_sent = []
        for ent in doc.ents:
            entity_text = ent.text.strip()
            if (ent.label_ in ['PERSON', 'ORG', 'GPE', 'DATE', 'MONEY', 'PERCENT', 'TIME', 'CARDINAL'] and
                MIN_ENTITY_LENGTH <= len(entity_text) <= MAX_ENTITY_LENGTH and
                not re.match(r'^[a-z]\.\s', entity_text) and
                not entity_text.startswith('•') and
                len(entity_text.split()) <= 4 and
                not re.match(r'^\d+\.$', entity_text)):
                entity_pool.setdefault(ent.label_, set()).add(entity_text)
                ents_in_sent.append((entity_text, ent.label_))
        sent_entities.append(ents_in_sent)
    return entity_pool, sent_entities


def generate_question_with_validation(sentence, answer, context=""):
    """Generate question with better prompting and validation"""
    answer = answer.strip()
    if not answer or len(answer) < 2:
        return None

    strategies = [
        f"generate question: {sentence.replace(answer, f'<hl> {answer} <hl>', 1)}",
        f"question: {answer} context: {sentence}",
        f"ask about: {answer} from: {sentence}"
    ]

    best_question = None
    best_score = 0

    for strategy in strategies:
        try:
            inputs = t5_tokenizer.encode(strategy, return_tensors="pt", max_length=512, truncation=True)
            outputs = t5_model.generate(
                inputs, 
                max_length=64, 
                num_beams=4, 
                temperature=0.8,
                do_sample=True,
                early_stopping=True,
                repetition_penalty=1.2
            )
            question = t5_tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
            score = score_question_quality(question, answer, sentence)
            if score > best_score:
                best_score = score
                best_question = question
        except Exception:
            continue
    return best_question if best_score > 0.5 else None


def score_question_quality(question, answer, context):
    if not question or len(question) < 10:
        return 0
    score = 1.0
    if answer.lower() in question.lower():
        score *= 0.3
    if not question.endswith('?'):
        score *= 0.7
    if len(question.split()) < 4:
        score *= 0.5
    question_words = ['what', 'who', 'where', 'when', 'why', 'how', 'which']
    if any(qw in question.lower() for qw in question_words):
        score *= 1.2
    if qa_pipeline:
        try:
            result = qa_pipeline(question=question, context=context)
            roberta_answer = result['answer'].lower().strip()
            expected_answer = answer.lower().strip()
            if expected_answer in roberta_answer or roberta_answer in expected_answer:
                score *= (1.0 + result['score'])
            else:
                score *= 0.5
        except:
            pass
    return min(score, 2.0)


def generate_smart_distractors(correct_answer, entity_pool, sentence, difficulty='medium'):
    doc = nlp(correct_answer)
    correct_ents = [ent for ent in doc.ents]
    correct_label = correct_ents[0].label_ if correct_ents else 'MISC'

    distractors = []
    if correct_label in entity_pool:
        same_type = [e for e in entity_pool[correct_label] if e != correct_answer]
        distractors.extend(same_type[:2])

    type_similarity = {
        'PERSON': ['ORG', 'GPE'],
        'ORG': ['PERSON', 'GPE'],
        'GPE': ['PERSON', 'ORG'],
        'DATE': ['TIME', 'CARDINAL'],
        'TIME': ['DATE', 'CARDINAL'],
        'CARDINAL': ['DATE', 'TIME', 'MONEY', 'PERCENT'],
        'MONEY': ['CARDINAL', 'PERCENT'],
        'PERCENT': ['CARDINAL', 'MONEY']
    }

    if difficulty == 'hard':
        related_types = type_similarity.get(correct_label, [])[:1]
    elif difficulty == 'easy':
        all_types = list(entity_pool.keys())
        related_types = [t for t in all_types if t != correct_label][-2:]
    else:
        related_types = type_similarity.get(correct_label, [])[:2]

    for rel_type in related_types:
        if rel_type in entity_pool:
            related_entities = list(entity_pool[rel_type])[:2]
            distractors.extend(related_entities)

    sent_doc = nlp(sentence)
    for ent in sent_doc.ents:
        if (ent.text != correct_answer and len(ent.text.strip()) > 1 and ent.text not in distractors):
            distractors.append(ent.text)

    clean_distractors = []
    seen = set()
    for d in distractors:
        d_clean = d.strip()
        if (d_clean.lower() not in seen and 
            d_clean.lower() != correct_answer.lower() and
            len(d_clean) > 1 and
            not re.match(r'^[a-z]\.\s*', d_clean) and
            not d_clean.startswith('•')):
            seen.add(d_clean.lower())
            clean_distractors.append(d_clean)
    return clean_distractors


def generate_high_quality_mcq(sentence, difficulty, entity_pool, sent_entities, index):
    if (len(sentence.split()) < 5 or
        sentence.startswith('a.') or
        sentence.startswith('•') or
        re.match(r'^\d+\.', sentence.strip())):
        return None

    doc = nlp(sentence)
    entities = [ent for ent in doc.ents 
                if (ent.label_ in entity_pool and 
                    len(ent.text.strip()) > 1 and
                    len(ent.text.split()) <= 3 and
                    not ent.text.strip().startswith('a.') and
                    not ent.text.strip().startswith('•'))]
    if not entities:
        return None

    scored_entities = []
    for ent in entities:
        quality_score = 1.0
        if difficulty == 'easy' and ent.label_ in ['PERSON', 'ORG']:
            quality_score += 0.5
        elif difficulty == 'hard' and ent.label_ in ['DATE', 'CARDINAL', 'PERCENT']:
            quality_score += 0.5
        if difficulty == 'easy' and len(ent.text) > 5:
            quality_score += 0.3
        elif difficulty == 'hard' and len(ent.text) <= 5:
            quality_score += 0.3
        scored_entities.append((ent, quality_score))

    if not scored_entities:
        return None

    best_entity = max(scored_entities, key=lambda x: x[1])[0]
    correct_answer = best_entity.text.strip()
    question = generate_question_with_validation(sentence, correct_answer)
    if not question:
        return None

    distractors = generate_smart_distractors(correct_answer, entity_pool, sentence, difficulty)
    if len(distractors) < 3:
        all_entities = []
        for entity_set in entity_pool.values():
            all_entities.extend([e for e in entity_set if e != correct_answer])
        additional_distractors = random.sample(all_entities, min(3 - len(distractors), len(all_entities)))
        distractors.extend(additional_distractors)

    if len(distractors) < 3:
        return None

    choices = [correct_answer] + distractors[:3]
    random.shuffle(choices)
    choice_map = dict(zip(['A', 'B', 'C', 'D'], choices))
    correct_letter = next(k for k, v in choice_map.items() if v == correct_answer)

    return {
        "question": question,
        "choices": choice_map,
        "correct": correct_letter,
        "confidence": 0.8
    }


def generate_true_false_improved(sentence, difficulty, entity_pool, sent_entities, index):
    if (len(sentence.split()) < 5 or
        sentence.startswith('a.') or
        sentence.startswith('•')):
        return None

    doc = nlp(sentence)
    entities = [ent for ent in doc.ents 
                if (ent.label_ in entity_pool and len(ent.text.strip()) > 1)]
    if not entities:
        return None

    make_false = random.random() < 0.6
    if make_false:
        entity_to_replace = random.choice(entities)
        distractors = generate_smart_distractors(
            entity_to_replace.text, entity_pool, sentence, difficulty
        )
        if distractors:
            replacement = random.choice(distractors[:3])
            modified_sentence = sentence.replace(entity_to_replace.text, replacement, 1)
            return {
                "question": modified_sentence,
                "choices": {"True": "True", "False": "False"},
                "correct": "False"
            }
    return {
        "question": sentence,
        "choices": {"True": "True", "False": "False"},
        "correct": "True"
    }


def generate_fill_blank_improved(sentence, difficulty, entity_pool, sent_entities, index):
    if (len(sentence.split()) < 5 or
        sentence.startswith('a.') or
        sentence.startswith('•')):
        return None

    doc = nlp(sentence)
    entities = [ent for ent in doc.ents 
                if (ent.label_ in entity_pool and len(ent.text.strip()) > 1 and len(ent.text.split()) <= 3)]
    if not entities:
        return None

    if difficulty == 'easy':
        entity_to_blank = max(entities, key=lambda e: len(e.text))
    elif difficulty == 'hard':
        entity_to_blank = min(entities, key=lambda e: len(e.text))
    else:
        entity_to_blank = random.choice(entities)

    blank_styles = {
        'easy': f"_____ ({entity_to_blank.label_.lower()})",
        'medium': "_____",
        'hard': "___"
    }

    blank = blank_styles.get(difficulty, "_____")
    question = sentence.replace(entity_to_blank.text, blank, 1)
    return {
        "question": question,
        "choices": {},
        "correct": entity_to_blank.text
    }


@app.route('/convert', methods=['POST'])
def convert():
    file = request.files.get('files[]')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = ''.join([page.extract_text() or '' for page in pdf_reader.pages])
        sentences = advanced_text_cleaning(text)
        entity_pool, sent_entities = extract_quality_entities(sentences)

        quality_sentences = [s for s in sentences 
                             if (len(s.split()) >= 5 and 
                                 not s.strip().startswith('a.') and
                                 not s.strip().startswith('•') and
                                 not re.match(r'^\d+\.', s.strip()))]
        if not quality_sentences:
            return jsonify({'error': 'No quality sentences found in PDF'}), 400

        num_sets = min(int(request.form.get('numSets', 1)), 3)
        sets = []
        current_sentence = 0

        for i in range(1, num_sets + 1):
            set_questions = int(request.form.get(f'set-{i}-questions', 5))
            difficulty = request.form.get(f'set-{i}-difficulty', 'easy').lower()
            question_type = request.form.get(f'set-{i}-question-type', 'multiple-choice').lower()

            questions = []
            answers = []
            count = 0
            attempts = 0
            max_attempts = min(len(quality_sentences) * 3, 100)

            while count < set_questions and attempts < max_attempts:
                if current_sentence >= len(quality_sentences):
                    current_sentence = 0
                sentence = quality_sentences[current_sentence]
                current_sentence += 1
                attempts += 1

                generated = None
                try:
                    if question_type == 'multiple-choice':
                        generated = generate_high_quality_mcq(sentence, difficulty, entity_pool, sent_entities, current_sentence - 1)
                    elif question_type == 'true-false':
                        generated = generate_true_false_improved(sentence, difficulty, entity_pool, sent_entities, current_sentence - 1)
                    elif question_type == 'fill-blank':
                        generated = generate_fill_blank_improved(sentence, difficulty, entity_pool, sent_entities, current_sentence - 1)
                except Exception as e:
                    print(f"Error generating question: {e}")
                    continue

                if generated and generated.get('question'):
                    count += 1

                    # ✅ Add placeholder answers if no choices exist
                    choices = generated["choices"]
                    if not choices:
                        choices = {
                            "A": f"Correct Answer {count}",
                            "B": f"Possible Answer {count}",
                            "C": f"Alternative {count}",
                            "D": f"Guess {count}"
                        }

                    questions.append({
                        "number": count,
                        "question": generated["question"],
                        "choices": choices,
                        "confidence": generated.get("confidence", 0.5)
                    })
                    answers.append(f"{count}. {generated['correct']}")

            sets.append({
                'set': f"Part {romanize(i)}",
                'difficulty': difficulty.title(),
                'question_type': question_type.replace('-', ' ').title(),
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

    except Exception as e:
        print(f"Error in convert route: {e}")
        return jsonify({'error': f'Failed to process PDF: {str(e)}'}), 500


@app.route('/validate-question', methods=['POST'])
def validate_question():
    data = request.json
    question = data.get('question')
    context = data.get('context')
    expected_answer = data.get('expected_answer')
    if not all([question, context, expected_answer]):
        return jsonify({'error': 'Missing required fields'}), 400
    if not qa_pipeline:
        return jsonify({'error': 'RoBERTa model not available'}), 500
    try:
        result = qa_pipeline(question=question, context=context)
        predicted = result['answer'].lower().strip()
        expected = expected_answer.lower().strip()
        is_similar = expected in predicted or predicted in expected
        return jsonify({
            'roberta_answer': result['answer'],
            'confidence': result['score'],
            'expected_answer': expected_answer,
            'is_similar': is_similar,
            'quality_score': result['score'] if is_similar else 0
        })
    except Exception as e:
        return jsonify({'error': f'Validation failed: {str(e)}'}), 500


if __name__ == '__main__':
    import os
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    app.run(debug=debug_mode)
