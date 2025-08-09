from flask import Flask, request, jsonify
from flask_cors import CORS
import PyPDF2
import random
import re
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


def clean_and_split_text(text):
    text = re.sub(r'\s+', ' ', text)  # normalize whitespace
    doc = nlp(text)
    sentences = [sent.text.strip() for sent in doc.sents if len(sent.text.split()) > 4]
    if not sentences:  # fallback if spaCy sentence detection fails
        sentences = [s.strip() for s in re.split(r'(?<=[.!?]) +', text) if len(s.split()) > 4]
    return sentences


def extract_entities(sentences):
    """Extract entities per sentence and build pools."""
    entity_pool = {}
    sent_entities = []

    for sent in sentences:
        doc = nlp(sent)
        ents_in_sent = []
        for ent in doc.ents:
            if ent.label_ in ['PERSON', 'ORG', 'GPE', 'DATE', 'NORP', 'MONEY', 'PERCENT', 'TIME', 'CARDINAL']:
                entity_pool.setdefault(ent.label_, set()).add(ent.text)
                ents_in_sent.append((ent.text, ent.label_))
        sent_entities.append(ents_in_sent)
    return entity_pool, sent_entities


def generate_question(sentence, answer):
    highlighted = sentence.replace(answer, f"<hl> {answer} <hl>", 1)
    input_text = f"generate question: {highlighted}"
    inputs = tokenizer.encode(input_text, return_tensors="pt")
    outputs = model.generate(inputs, max_length=64, num_beams=4, early_stopping=True)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)


def get_context_entities(sent_entities, index, window=2):
    """Return entities from same and adjacent sentences for context-aware hard mode."""
    context_entities = set()
    start = max(0, index - window)
    end = min(len(sent_entities), index + window + 1)
    
    for i in range(start, end):
        for ent_text, ent_label in sent_entities[i]:
            context_entities.add((ent_text, ent_label))
    return context_entities


def filter_distractors(correct_text, correct_label, entity_pool, difficulty, context_entities=None):
    """
    Returns a list of distractors based on difficulty:
    - Easy: distractors from completely different entity types (very obviously wrong)
    - Medium: distractors from related but different entity types 
    - Hard: distractors from same entity type, preferably from nearby context (very confusing)
    """
    distractors = []
    
    # Define entity type relationships for better difficulty scaling
    type_groups = {
        'PEOPLE': ['PERSON'],
        'ORGANIZATIONS': ['ORG'], 
        'PLACES': ['GPE'],
        'NUMBERS': ['DATE', 'MONEY', 'PERCENT', 'TIME', 'CARDINAL'],
        'GROUPS': ['NORP']
    }
    
    correct_group = None
    for group, types in type_groups.items():
        if correct_label in types:
            correct_group = group
            break

    if difficulty == 'easy':
        # Use entities from COMPLETELY different groups - most obviously wrong
        wrong_groups = [g for g in type_groups.keys() if g != correct_group]
        all_wrong_entities = []
        
        for wrong_group in wrong_groups:
            for entity_type in type_groups[wrong_group]:
                if entity_type in entity_pool:
                    all_wrong_entities.extend(list(entity_pool[entity_type]))
        
        # Remove correct answer and prioritize very different types
        distractors = [e for e in all_wrong_entities if e != correct_text]
        
        # Shuffle and prioritize most different types first
        random.shuffle(distractors)
        
    elif difficulty == 'medium':
        # Mix same group and different groups - moderately confusing
        same_group_entities = []
        different_group_entities = []
        
        # Get entities from same group
        if correct_group:
            for entity_type in type_groups[correct_group]:
                if entity_type in entity_pool:
                    same_group_entities.extend(list(entity_pool[entity_type]))
        
        # Get entities from different groups  
        for group, types in type_groups.items():
            if group != correct_group:
                for entity_type in types:
                    if entity_type in entity_pool:
                        different_group_entities.extend(list(entity_pool[entity_type]))
        
        # Remove correct answer
        same_group_entities = [e for e in same_group_entities if e != correct_text]
        different_group_entities = [e for e in different_group_entities if e != correct_text]
        
        # Mix: 60% same group, 40% different group for medium difficulty
        distractors = same_group_entities + different_group_entities[:len(same_group_entities)]
        random.shuffle(distractors)
        
    else:  # hard
        # Same entity type, preferably from nearby context - most challenging
        if context_entities:
            # Prioritize exact same type from context
            context_same_type = [e for e, l in context_entities 
                               if l == correct_label and e != correct_text]
            
            # Also get same group but different type from context
            context_same_group = []
            if correct_group:
                for entity_type in type_groups[correct_group]:
                    context_same_group.extend([e for e, l in context_entities 
                                             if l == entity_type and e != correct_text])
            
            if len(context_same_type) >= 2:
                # Best case: multiple same-type from context
                distractors = context_same_type
            elif context_same_group:
                # Good case: same group from context + some same type from document
                global_same_type = list(entity_pool.get(correct_label, set()) - {correct_text})
                distractors = context_same_group + global_same_type[:2]
            else:
                # Fallback: same type from document
                distractors = list(entity_pool.get(correct_label, set()) - {correct_text})
        else:
            distractors = list(entity_pool.get(correct_label, set()) - {correct_text})
        
        random.shuffle(distractors)

    # Remove duplicates while preserving order
    seen = set()
    unique_distractors = []
    for d in distractors:
        if d not in seen and d != correct_text and len(d.strip()) > 0:
            seen.add(d)
            unique_distractors.append(d)
    
    return unique_distractors


def select_entity_for_question(doc_entities, difficulty, context_entities=None):
    """Select which entity to use based on difficulty."""
    if not doc_entities:
        return None
    
    # Categorize entities by type and prominence
    prominent_types = ['PERSON', 'ORG']  # Usually more obvious (names, companies)
    location_types = ['GPE']  # Places - medium difficulty 
    subtle_types = ['DATE', 'MONEY', 'PERCENT', 'TIME', 'CARDINAL', 'NORP']  # Less obvious details
    
    prominent_entities = [e for e in doc_entities if e.label_ in prominent_types]
    location_entities = [e for e in doc_entities if e.label_ in location_types]
    subtle_entities = [e for e in doc_entities if e.label_ in subtle_types]
    
    if difficulty == 'easy':
        # Prefer well-known entities (people, organizations) - longest ones
        if prominent_entities:
            # Sort by length and familiarity
            return max(prominent_entities, key=lambda e: len(e.text))
        elif location_entities:
            return max(location_entities, key=lambda e: len(e.text))
        else:
            return max(doc_entities, key=lambda e: len(e.text))
    
    elif difficulty == 'medium':
        # Mix of prominent and location entities, avoid the most obvious
        candidates = prominent_entities + location_entities
        if candidates:
            return random.choice(candidates)
        else:
            return random.choice(doc_entities)
    
    else:  # hard
        # Prefer subtle details, numbers, dates - things that require careful reading
        if subtle_entities:
            # Choose shortest subtle entity (harder to notice)
            return min(subtle_entities, key=lambda e: len(e.text))
        elif location_entities:
            # If no subtle entities, use shortest location
            return min(location_entities, key=lambda e: len(e.text))
        else:
            return min(doc_entities, key=lambda e: len(e.text))


def generate_mcq(sentence, difficulty, entity_pool, sent_entities, index):
    doc = nlp(sentence)
    entities = [ent for ent in doc.ents if ent.label_ in entity_pool and ent.text.strip()]
    
    if not entities:
        return None
    
    context_entities = get_context_entities(sent_entities, index)
    
    # Filter entities by difficulty preference FIRST
    if difficulty == 'easy':
        # Strongly prefer people and organizations
        preferred = [e for e in entities if e.label_ in ['PERSON', 'ORG']]
        entities = preferred if preferred else entities
    elif difficulty == 'hard':
        # Strongly prefer dates, numbers, and subtle details
        preferred = [e for e in entities if e.label_ in ['DATE', 'MONEY', 'PERCENT', 'TIME', 'CARDINAL']]
        entities = preferred if preferred else entities
    
    # Select entity based on difficulty from filtered list
    selected_entity = select_entity_for_question(entities, difficulty, context_entities)
    if not selected_entity:
        return None
    
    question = generate_question(sentence, selected_entity.text)
    distractors = filter_distractors(selected_entity.text, selected_entity.label_, 
                                   entity_pool, difficulty, context_entities)
    
    # Build choices (correct + 3 distractors)
    choices = [selected_entity.text]
    if len(distractors) >= 3:
        choices.extend(distractors[:3])
    else:
        # Need more distractors - get from all entities
        all_entities = set()
        for entities_set in entity_pool.values():
            all_entities.update(entities_set)
        
        additional_needed = 3 - len(distractors)
        additional_distractors = list(all_entities - set(choices) - set(distractors))
        random.shuffle(additional_distractors)
        
        choices.extend(distractors)
        choices.extend(additional_distractors[:additional_needed])
    
    # Ensure exactly 4 choices
    while len(choices) < 4:
        # Last resort - add generic placeholders
        choices.append(f"Option {len(choices)}")
    
    choices = choices[:4]  # Trim to exactly 4
    random.shuffle(choices)
    
    choice_map = dict(zip(["A", "B", "C", "D"], choices))
    correct_letter = next(k for k, v in choice_map.items() if v == selected_entity.text)
    
    return {
        "question": question,
        "choices": choice_map,
        "correct": correct_letter
    }


def generate_true_false(sentence, difficulty, entity_pool, sent_entities, index):
    doc = nlp(sentence)
    entities = [ent for ent in doc.ents if ent.label_ in entity_pool and ent.text.strip()]
    
    # Filter entities by difficulty preference FIRST
    if difficulty == 'easy':
        # Strongly prefer people and organizations for easy questions
        preferred = [e for e in entities if e.label_ in ['PERSON', 'ORG']]
        entities = preferred if preferred else entities
    elif difficulty == 'hard':
        # Strongly prefer dates, numbers, and subtle details for hard questions
        preferred = [e for e in entities if e.label_ in ['DATE', 'MONEY', 'PERCENT', 'TIME', 'CARDINAL']]
        entities = preferred if preferred else entities
    
    # Difficulty affects probability of making it false and type of replacement
    if difficulty == 'easy':
        make_false_prob = 0.6  # More likely to be false (easier to spot)
    elif difficulty == 'medium':
        make_false_prob = 0.5  # 50/50
    else:  # hard
        make_false_prob = 0.7  # More likely to be false but with subtle changes
    
    is_true = random.random() > make_false_prob
    modified_sentence = sentence
    correct_answer = "True"
    
    if not is_true and entities:
        context_entities = get_context_entities(sent_entities, index)
        
        # Select entity to replace based on difficulty
        entity_to_replace = select_entity_for_question(entities, difficulty, context_entities)
        if not entity_to_replace:
            entity_to_replace = random.choice(entities)
        
        # Get replacement based on difficulty
        distractors = filter_distractors(entity_to_replace.text, entity_to_replace.label_, 
                                       entity_pool, difficulty, context_entities)
        
        if distractors:
            if difficulty == 'hard':
                # Use most similar replacement for hard difficulty
                replacement = distractors[0]  # Already filtered for context similarity
            else:
                # Use random replacement for easy/medium
                replacement = random.choice(distractors[:5])  # From top candidates
            
            modified_sentence = sentence.replace(entity_to_replace.text, replacement, 1)
            correct_answer = "False"
    
    return {
        "question": modified_sentence,
        "choices": {"True": "True", "False": "False"},
        "correct": correct_answer
    }


def generate_fill_blank(sentence, difficulty, entity_pool, sent_entities, index):
    doc = nlp(sentence)
    entities = [ent for ent in doc.ents if ent.label_ in entity_pool and ent.text.strip()]
    
    if not entities:
        return None
    
    # Filter entities by difficulty preference FIRST
    if difficulty == 'easy':
        # Strongly prefer people and organizations
        preferred = [e for e in entities if e.label_ in ['PERSON', 'ORG']]
        entities = preferred if preferred else entities
    elif difficulty == 'hard':
        # Strongly prefer dates, numbers, and subtle details
        preferred = [e for e in entities if e.label_ in ['DATE', 'MONEY', 'PERCENT', 'TIME', 'CARDINAL']]
        entities = preferred if preferred else entities
    
    context_entities = get_context_entities(sent_entities, index)
    
    # Select entity to blank based on difficulty
    entity_to_blank = select_entity_for_question(entities, difficulty, context_entities)
    if not entity_to_blank:
        return None
    
    # Create different blank styles based on difficulty
    if difficulty == 'easy':
        # Longer blank with hint
        blank = f"_____({entity_to_blank.label_.lower()})"
    elif difficulty == 'medium':
        # Standard blank
        blank = "_____"
    else:  # hard
        # Shorter blank, less obvious
        blank = "___"
    
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

    pdf_reader = PyPDF2.PdfReader(file)
    text = ''.join([page.extract_text() or '' for page in pdf_reader.pages])

    sentences = clean_and_split_text(text)
    entity_pool, sent_entities = extract_entities(sentences)

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
        max_attempts = len(sentences) * 2  # Prevent infinite loops

        while count < set_questions and current_sentence < len(sentences) and attempts < max_attempts:
            sentence = sentences[current_sentence]
            current_sentence += 1
            attempts += 1

            generated = None
            if question_type == 'multiple-choice':
                generated = generate_mcq(sentence, difficulty, entity_pool, sent_entities, current_sentence - 1)
            elif question_type == 'true-false':
                generated = generate_true_false(sentence, difficulty, entity_pool, sent_entities, current_sentence - 1)
            elif question_type == 'fill-blank':
                generated = generate_fill_blank(sentence, difficulty, entity_pool, sent_entities, current_sentence - 1)

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


if __name__ == '__main__':
    import os
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))