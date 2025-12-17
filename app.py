from flask import Flask, request, jsonify
import json
from datetime import datetime

app = Flask(__name__)

DATA_FILE = 'students.json'

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/', methods=['GET', 'POST'])
def track():
    data = request.args.to_dict()
    data['received_at'] = datetime.now().isoformat()
    data['ip'] = request.remote_addr

    students = load_data()
    device_id = data.get('device_id', 'unknown')
    students[device_id] = data
    save_data(students)

    return "OK", 200

@app.route('/view')
def view():
    students = load_data()
    html = "<h1>طلاب الامتحانات - Live View</h1><table border='1'><tr><th>Device ID</th><th>Quiz</th><th>Slide</th><th>Answers</th><th>Last Update</th></tr>"
    for id, info in students.items():
        answers = info.get('answers', '[]')[:100] + "..." if len(info.get('answers', '')) > 100 else info.get('answers', '')
        html += f"<tr><td>{id}</td><td>{info.get('quiz', '')}</td><td>{info.get('slide', '')}</td><td>{answers}</td><td>{info.get('received_at', '')}</td></tr>"
    html += "</table><meta http-equiv='refresh' content='30'>"
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)  # Render يستخدم port 10000 في Free
