from flask import Flask, request
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
    data['ip'] = request.remote_addr or 'unknown'

    students = load_data()
    device_id = data.get('device_id', 'unknown')
    students[device_id] = data
    save_data(students)

    return "OK", 200

@app.route('/view')
def view():
    students = load_data()
    html = "<h1 style='color:#00ff88; text-align:center; font-family:Arial;'>طلاب الامتحانات - Live View</h1>"
    html += "<table border='1' style='width:100%; border-collapse:collapse; margin:20px auto;'><tr style='background:#22c55e; color:white;'><th>Device ID</th><th>Quiz</th><th>Slide</th><th>Answers</th><th>Last Update</th></tr>"
    for id, info in sorted(students.items(), key=lambda x: x[1]['received_at'], reverse=True):
        answers = str(info.get('answers', ''))[:150].replace('<', '&lt;') + ("..." if len(str(info.get('answers', ''))) > 150 else "")
        html += f"<tr><td>{id}</td><td>{info.get('quiz', '')}</td><td>{info.get('slide', '')}</td><td>{answers}</td><td>{info.get('received_at', '')}</td></tr>"
    html += "</table>"
    html += "<meta http-equiv='refresh' content='30'>"
    html += "<p style='text-align:center; color:#86efac;'>تحديث تلقائي كل 30 ثانية</p>"
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)  # Wasmer يستخدم port 10000
