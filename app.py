from flask import Flask,render_template,request

app = Flask(__name__)



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
