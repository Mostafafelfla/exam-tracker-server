from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import json
from datetime import datetime, timedelta
import os
from collections import defaultdict
import threading
import time

app = Flask(__name__)
# تفعيل CORS للسماح بالتحكم من ملفات HTML المحلية
CORS(app, resources={r"/*": {"origins": "*"}})

# زيادة حجم البيانات المسموح بها لاستلام الصور
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# ملفات التخزين
DATA_FILE = '/tmp/exam_tracking_v6.json'
COMMANDS_FILE = '/tmp/exam_cmds_v6.json'

# القوائم في الذاكرة
students = defaultdict(dict)
pending_commands = defaultdict(list)

def load_data():
    global students, pending_commands
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                students.update(json.load(f))
        if os.path.exists(COMMANDS_FILE):
            with open(COMMANDS_FILE, 'r') as f:
                pending_commands.update(json.load(f))
    except Exception as e:
        print(f"📂 Load Error: {e}")

def save_data():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(dict(students), f)
        with open(COMMANDS_FILE, 'w') as f:
            json.dump(dict(pending_commands), f)
    except Exception as e:
        print(f"💾 Save Error: {e}")

load_data()

# تنظيف البيانات القديمة تلقائياً
def cleanup_loop():
    while True:
        now = datetime.utcnow()
        to_remove = []
        for sid, data in students.items():
            last = data.get('last_update')
            if last:
                if (now - datetime.fromisoformat(last)) > timedelta(hours=12):
                    to_remove.append(sid)
        for sid in to_remove: del students[sid]
        time.sleep(3600)

threading.Thread(target=cleanup_loop, daemon=True).start()

# --- المسارات الرئيسية ---

@app.route('/', methods=['GET', 'POST'])
def track():
    """المسار الرئيسي لاستلام البيانات من ملف HTML"""
    try:
        if request.method == 'POST':
            data = request.json or request.form.to_dict()
        else:
            data = request.args.to_dict()

        if not data or 'device_id' not in data:
            return jsonify({"status": "error", "message": "no device_id"}), 400

        device_id = data['device_id']
        
        # تحديث بيانات الطالب
        if device_id not in students:
            students[device_id] = {'first_seen': datetime.utcnow().isoformat()}
        
        students[device_id].update(data)
        students[device_id]['last_update'] = datetime.utcnow().isoformat()
        students[device_id]['ip_address'] = request.remote_addr
        
        # إذا كانت البيانات تحتوي على صورة (Screenshot)
        if data.get('event') == 'screenshot_data':
            print(f"📸 استلام لقطة شاشة من {device_id}")

        save_data()
        return jsonify({"status": "success", "device_id": device_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_commands', methods=['GET'])
def get_commands():
    """المسار الذي يسحب منه ملف HTML الأوامر"""
    device_id = request.args.get('device_id')
    if not device_id: return jsonify([])
    
    cmds = pending_commands.get(device_id, [])
    if cmds:
        pending_commands[device_id] = [] # مسح الأوامر بعد سحبها
        save_data()
    return jsonify(cmds)

@app.route('/send_command', methods=['POST'])
def send_command():
    """المسار الذي يرسل منه تطبيق الادمن الأوامر"""
    try:
        data = request.json
        device_id = data.get('device_id')
        if not device_id: return jsonify({"status": "error"}), 400
        
        pending_commands[device_id].append(data)
        save_data()
        return jsonify({"status": "success", "message": "Command Queued"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/students')
def api_students():
    """API لجلب قائمة الطلاب لتطبيق الادمن"""
    active_cutoff = datetime.utcnow() - timedelta(minutes=10)
    result = []
    for sid, data in students.items():
        if datetime.fromisoformat(data['last_update']) > active_cutoff:
            result.append(data)
    return jsonify(result)

@app.route('/view')
def view_dashboard():
    """واجهة الويب الاحترافية"""
    load_data()
    now = datetime.utcnow()
    rows = ""
    active_count = 0
    
    sorted_students = sorted(students.items(), key=lambda x: x[1].get('last_update', ''), reverse=True)

    for idx, (sid, data) in enumerate(sorted_students, 1):
        last_up = datetime.fromisoformat(data.get('last_update', now.isoformat()))
        diff = (now - last_up).total_seconds()
        
        status_class = "status-active" if diff < 60 else "status-inactive"
        status_text = "🟢 نشط" if diff < 60 else "🔴 غير متصل"
        if diff < 60: active_count += 1
        
        rows += f"""
        <tr>
            <td>{idx}</td>
            <td><span class="device-id">{sid}</span></td>
            <td>{data.get('quiz', 'غير معروف')}</td>
            <td>{data.get('answers_count', '0')}</td>
            <td>{data.get('time_left', '0')} ث</td>
            <td><span class="{status_class}">{status_text}</span></td>
            <td>{last_up.strftime('%H:%M:%S')}</td>
            <td>{data.get('ip_address', 'unknown')}</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Octopus Control - Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ background: #0f172a; color: #f1f5f9; font-family: 'Segoe UI', sans-serif; }}
            .container {{ margin-top: 50px; }}
            .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 15px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
            h1 {{ color: #22c55e; font-weight: 800; text-shadow: 0 0 10px rgba(34,197,94,0.2); }}
            table {{ color: #cbd5e1 !important; }}
            th {{ color: #22c55e; border-bottom: 2px solid #334155 !important; }}
            .device-id {{ font-family: 'Consolas', monospace; color: #38bdf8; background: #000; padding: 2px 8px; border-radius: 5px; }}
            .status-active {{ color: #22c55e; font-weight: bold; }}
            .status-inactive {{ color: #ef4444; font-weight: bold; }}
            .stat-card {{ background: #0f172a; border-radius: 10px; padding: 15px; text-align: center; border: 1px solid #334155; }}
            .stat-val {{ font-size: 2rem; font-weight: bold; color: #22c55e; }}
        </style>
        <script>setTimeout(() => location.reload(), 10000);</script>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h1>🐙 Octopus Dashboard</h1>
                    <div class="text-end">
                        <div class="badge bg-success">متصل بالسيرفر</div>
                        <div class="text-muted small">تحديث تلقائي كل 10 ثوانٍ</div>
                    </div>
                </div>
                
                <div class="row g-3 mb-4">
                    <div class="col-md-4"><div class="stat-card"><div class="stat-val">{len(students)}</div><div>إجمالي الأجهزة</div></div></div>
                    <div class="col-md-4"><div class="stat-card"><div class="stat-val">{active_count}</div><div>نشط الآن</div></div></div>
                    <div class="col-md-4"><div class="stat-card"><div class="stat-val">{datetime.now().strftime('%H:%M:%S')}</div><div>وقت السيرفر</div></div></div>
                </div>

                <div class="table-responsive">
                    <table class="table table-dark table-hover">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>معرف الجهاز</th>
                                <th>الامتحان</th>
                                <th>الإجابات</th>
                                <th>المتبقي</th>
                                <th>الحالة</th>
                                <th>آخر ظهور</th>
                                <th>IP</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
