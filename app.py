from flask import Flask,render_template,request,jsonify
 
from flask_cors import CORS
app = Flask(__name__)


CORS(app, origins=["http://127.0.0.1:5500", "https://sample-render-hosting-1.onrender.com"])

@app.route('/convert', methods=['POST'])
def convert():
    # Static questions to return
    static_questions = [
        {
            'question': 'What is the capital of France?',
            'options': ['Paris', 'London', 'Berlin', 'Rome'],
            'answer': 'A'
        },
        {
            'question': 'Which is the largest planet in our solar system?',
            'options': ['Earth', 'Jupiter', 'Mars', 'Saturn'],
            'answer': 'B'
        },
        {
            'question': 'What is the chemical symbol for water?',
            'options': ['O2', 'H2O', 'CO2', 'N2'],
            'answer': 'B'
        }
    ]

    return jsonify({'quiz': {'Set-A': static_questions}})


 

if __name__ == '__main__':
    app.run(debug=True)
