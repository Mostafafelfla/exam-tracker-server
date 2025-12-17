from flask import Flask, request
import json
from datetime import datetime
import os

app = Flask(__name__)

DATA_FILE = 'students.json'

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
    data = request.args.to_dict()
    data['received_at'] = datetime.utcnow().isoformat()
    data['ip'] = request.remote_addr or 'unknown'

    students = load_data()
    device_id = data.get('device_id', 'unknown')
    students[device_id] = data
    save_data(students)

    return "OK", 200

@app.route('/view')
def view():
    students = load_data()
    html = "<h1 style='color:#22c55e; text-align:center;'>طلاب الامتحانات - Live View</h1>"
    html += "<table border='1' style='width:90%; margin:20px auto; border-collapse:collapse;'><tr style='background:#22c55e;color:white;'><th>Device ID</th><th>Quiz</th><th>Slide</th><th>Answers</th><th>Last Update</th></tr>"
    for id, info in sorted(students.items(), key=lambda x: x[1]['received_at'], reverse=True):
        answers = str(info.get('answers', ''))[:150]
        html += f"<tr><td>{id}</td><td>{info.get('quiz', '')}</td><td>{info.get('slide', '')}</td><td>{answers}</td><td>{info.get('received_at', '')}</td></tr>"
    html += "</table>"
    html += "<meta http-equiv='refresh' content='30'>"
    return html
