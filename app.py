from flask import Flask, request, jsonify
import json
from datetime import datetime
import os

app = Flask(__name__)

DATA_FILE = '/tmp/students.json'

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, 'r') as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/', methods=['GET', 'POST'])
def track():
    data = request.form.to_dict() if request.method == 'POST' else request.args.to_dict()
    data['received_at'] = datetime.utcnow().isoformat()
    data['ip'] = request.remote_addr

    students = load_data()
    device_id = data.get('device_id', 'unknown')
    students[device_id] = data
    save_data(students)

    return jsonify({"status": "received", "device_id": device_id})

@app.route('/view')
def view():
    students = load_data()
    html = "<h1>طلاب الامتحانات - Live</h1><table border='1'><tr><th>Device ID</th><th>Quiz</th><th>Slide</th><th>Answers</th><th>Last Update</th></tr>"
    for id, info in students.items():
        html += f"<tr><td>{id}</td><td>{info.get('quiz', '')}</td><td>{info.get('slide', '')}</td><td>{info.get('answers', '')[:100]}</td><td>{info.get('received_at', '')}</td></tr>"
    html += "</table>"
    return html
