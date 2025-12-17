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
    if request.method == 'POST':
        data.update(request.form.to_dict())
    data['received_at'] = datetime.now().isoformat()
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
    html += "<table border='1' style='width:100%; border-collapse:collapse;'><tr style='background:#22c55e;color:white;'><th>Device ID</th><th>Quiz</th><th>Slide</th><th>Answers</th><th>Last Update</th></tr>"
    for id, info in students.items():
        answers = str(info.get('answers', ''))[:150] + "..." if len(str(info.get('answers', ''))) > 150 else info.get('answers', '')
        html += f"<tr><td>{id}</td><td>{info.get('quiz', '')}</td><td>{info.get('slide', '')}</td><td>{answers}</td><td>{info.get('received_at', '')}</td></tr>"
    html += "</table>"
    html += "<meta http-equiv='refresh' content='30'>"
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)  # Wasmer يستخدم port 10000
