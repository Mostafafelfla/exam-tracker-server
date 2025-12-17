from flask import Flask, request, jsonify, render_template_string
import json
from datetime import datetime, timedelta
import os
from collections import defaultdict
import threading
import time

app = Flask(__name__)

# ملف تخزين البيانات
DATA_FILE = '/tmp/exam_tracking_data.json'
COMMANDS_FILE = '/tmp/exam_commands.json'

# قوائم التخزين في الذاكرة للسرعة
students = defaultdict(dict)
pending_commands = defaultdict(list)

def load_data():
    """تحميل البيانات من الملف"""
    global students, pending_commands
    
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                students.update(json.load(f))
        
        if os.path.exists(COMMANDS_FILE):
            with open(COMMANDS_FILE, 'r') as f:
                pending_commands.update(json.load(f))
    except Exception as e:
        print(f"📂 خطأ في تحميل البيانات: {e}")

def save_data():
    """حفظ البيانات للملف"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(dict(students), f, indent=2)
        
        with open(COMMANDS_FILE, 'w') as f:
            json.dump(dict(pending_commands), f, indent=2)
    except Exception as e:
        print(f"💾 خطأ في حفظ البيانات: {e}")

# تحميل البيانات عند البدء
load_data()

def cleanup_old_data():
    """تنظيف البيانات القديمة"""
    now = datetime.utcnow()
    cutoff_time = now - timedelta(hours=24)  # احتفظ ببيانات 24 ساعة فقط
    
    # تنظيف الطلاب غير النشطين
    to_remove = []
    for device_id, data in students.items():
        last_update = data.get('last_update')
        if last_update:
            try:
                update_time = datetime.fromisoformat(last_update)
                if update_time < cutoff_time:
                    to_remove.append(device_id)
            except:
                to_remove.append(device_id)
    
    for device_id in to_remove:
        del students[device_id]
    
    # تنظيف الأوامر القديمة
    for device_id in list(pending_commands.keys()):
        if device_id not in students:
            del pending_commands[device_id]
    
    save_data()

# بدء التنظيف الدوري
def start_cleanup_thread():
    """بدء خيط التنظيف الدوري"""
    def cleanup_loop():
        while True:
            time.sleep(3600)  # كل ساعة
            cleanup_old_data()
            print(f"🧹 تم تنظيف البيانات - {datetime.utcnow().isoformat()}")
    
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()

start_cleanup_thread()

@app.route('/', methods=['GET', 'POST'])
def track():
    """استقبال البيانات من الطلاب"""
    try:
        # جمع البيانات
        if request.method == 'GET':
            data = request.args.to_dict()
        else:
            data = request.json or request.form.to_dict() or request.args.to_dict()
        
        # إضافة معلومات الإستقبال
        data['received_at'] = datetime.utcnow().isoformat()
        data['ip_address'] = request.remote_addr
        data['user_agent'] = request.headers.get('User-Agent', 'unknown')
        
        # استخراج device_id
        device_id = data.get('device_id', 'unknown')
        event_type = data.get('event', 'unknown')
        
        # تحديث بيانات الطالب
        students[device_id].update({
            **data,
            'last_update': data['received_at'],
            'device_id': device_id
        })
        
        # معالجة خاصة لكل نوع حدث
        if event_type == 'exam_opened':
            students[device_id]['first_seen'] = data['received_at']
            students[device_id]['status'] = 'active'
        
        elif event_type == 'heartbeat':
            students[device_id]['status'] = 'active'
            students[device_id]['heartbeat_count'] = students[device_id].get('heartbeat_count', 0) + 1
        
        elif event_type == 'exam_submitted':
            students[device_id]['submitted_at'] = data['received_at']
            students[device_id]['status'] = 'submitted'
        
        # حفظ البيانات
        save_data()
        
        print(f"📥 [{event_type}] من {device_id} - {data.get('quiz', 'unknown')}")
        
        return jsonify({
            "status": "success",
            "message": "تم استلام البيانات",
            "device_id": device_id,
            "timestamp": data['received_at']
        })
    
    except Exception as e:
        print(f"❌ خطأ في /track: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/commands', methods=['GET'])
def get_commands():
    """الحصول على الأوامر المعلقة للجهاز"""
    try:
        device_id = request.args.get('device_id')
        if not device_id:
            return jsonify([])
        
        # الحصول على الأوامر المعلقة
        commands = pending_commands.get(device_id, [])
        
        # مسح الأوامر بعد إرسالها
        if commands:
            pending_commands[device_id] = []
            save_data()
        
        return jsonify(commands)
    
    except Exception as e:
        print(f"❌ خطأ في /commands: {e}")
        return jsonify([])

@app.route('/send_command', methods=['POST', 'GET'])
def send_command():
    """إرسال أمر لجهاز محدد"""
    try:
        if request.method == 'GET':
            data = request.args.to_dict()
        else:
            data = request.json or request.form.to_dict()
        
        device_id = data.get('device_id')
        command_type = data.get('type')
        
        if not device_id or not command_type:
            return jsonify({"status": "error", "message": "يجب تحديد device_id و type"}), 400
        
        # إضافة الأمر للقائمة المعلقة
        pending_commands[device_id].append({
            "type": command_type,
            "data": data,
            "sent_at": datetime.utcnow().isoformat(),
            "command_id": f"cmd_{int(time.time())}"
        })
        
        # حفظ البيانات
        save_data()
        
        print(f"📤 أمر {command_type} أرسل لـ {device_id}")
        
        return jsonify({
            "status": "success",
            "message": "تم إرسال الأمر",
            "device_id": device_id,
            "command_type": command_type
        })
    
    except Exception as e:
        print(f"❌ خطأ في /send_command: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/view')
def view_students():
    """عرض الطلاب المتصلين"""
    # تنظيف القائمة من الطلاب غير النشطين
    active_students = {}
    now = datetime.utcnow()
    
    for device_id, data in students.items():
        last_update = data.get('last_update')
        if last_update:
            try:
                update_time = datetime.fromisoformat(last_update)
                # إذا كان التحديث في آخر 10 دقائق
                if (now - update_time).seconds < 600:
                    active_students[device_id] = data
            except:
                pass
    
    # ترتيب حسب آخر تحديث
    sorted_students = sorted(
        active_students.items(),
        key=lambda x: x[1].get('last_update', ''),
        reverse=True
    )
    
    # HTML لعرض البيانات
    html = """
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>👨‍🎓 الطلاب المتصلين - نظام تتبع الامتحانات</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            
            body {
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                color: #f1f5f9;
                min-height: 100vh;
                padding: 20px;
            }
            
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            
            header {
                text-align: center;
                padding: 30px 20px;
                background: rgba(30, 41, 59, 0.8);
                border-radius: 20px;
                margin-bottom: 30px;
                border: 2px solid #22c55e;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            }
            
            h1 {
                font-size: 2.8rem;
                color: #22c55e;
                margin-bottom: 10px;
                text-shadow: 0 2px 10px rgba(34, 197, 94, 0.3);
            }
            
            .stats {
                display: flex;
                justify-content: center;
                gap: 30px;
                margin-top: 20px;
                flex-wrap: wrap;
            }
            
            .stat-box {
                background: rgba(255, 255, 255, 0.1);
                padding: 15px 25px;
                border-radius: 12px;
                min-width: 180px;
                text-align: center;
                border: 1px solid rgba(34, 197, 94, 0.3);
            }
            
            .stat-number {
                font-size: 2.5rem;
                font-weight: bold;
                color: #22c55e;
                display: block;
            }
            
            .stat-label {
                font-size: 0.9rem;
                color: #94a3b8;
                margin-top: 5px;
            }
            
            .table-container {
                background: rgba(30, 41, 59, 0.9);
                border-radius: 15px;
                padding: 25px;
                margin-top: 30px;
                border: 1px solid rgba(34, 197, 94, 0.2);
                overflow-x: auto;
            }
            
            table {
                width: 100%;
                border-collapse: collapse;
                min-width: 1000px;
            }
            
            th {
                background: #1e40af;
                color: white;
                padding: 18px 15px;
                text-align: center;
                font-weight: 600;
                border-bottom: 3px solid #22c55e;
                position: sticky;
                top: 0;
            }
            
            td {
                padding: 15px;
                text-align: center;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                transition: background 0.3s;
            }
            
            tr:hover td {
                background: rgba(34, 197, 94, 0.1);
            }
            
            .status-active {
                color: #22c55e;
                background: rgba(34, 197, 94, 0.1);
                padding: 5px 15px;
                border-radius: 20px;
                font-weight: bold;
            }
            
            .status-inactive {
                color: #ef4444;
                background: rgba(239, 68, 68, 0.1);
                padding: 5px 15px;
                border-radius: 20px;
                font-weight: bold;
            }
            
            .status-submitted {
                color: #3b82f6;
                background: rgba(59, 130, 246, 0.1);
                padding: 5px 15px;
                border-radius: 20px;
                font-weight: bold;
            }
            
            .device-id {
                font-family: monospace;
                background: rgba(0, 0, 0, 0.3);
                padding: 5px 10px;
                border-radius: 5px;
                font-size: 0.9rem;
            }
            
            footer {
                text-align: center;
                margin-top: 40px;
                padding: 20px;
                color: #94a3b8;
                font-size: 0.9rem;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            .last-update {
                text-align: center;
                margin: 20px 0;
                color: #94a3b8;
                font-size: 0.9rem;
            }
            
            .auto-refresh {
                display: inline-block;
                background: #22c55e;
                color: white;
                padding: 8px 20px;
                border-radius: 25px;
                text-decoration: none;
                margin-top: 10px;
                transition: transform 0.3s;
            }
            
            .auto-refresh:hover {
                transform: scale(1.05);
            }
            
            @media (max-width: 768px) {
                .container {
                    padding: 10px;
                }
                
                h1 {
                    font-size: 2rem;
                }
                
                .stats {
                    gap: 15px;
                }
                
                .stat-box {
                    min-width: 140px;
                    padding: 10px 15px;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>👨‍🎓 الطلاب المتصلين - نظام تتبع الامتحانات</h1>
                <p style="color: #94a3b8; margin-top: 10px;">
                    📡 عرض مباشر للطلاب الذين يقومون بحل الامتحانات
                </p>
                
                <div class="stats">
                    <div class="stat-box">
                        <span class="stat-number" id="total-count">%TOTAL%</span>
                        <span class="stat-label">إجمالي الطلاب</span>
                    </div>
                    <div class="stat-box">
                        <span class="stat-number" id="active-count">%ACTIVE%</span>
                        <span class="stat-label">طلاب نشطين</span>
                    </div>
                    <div class="stat-box">
                        <span class="stat-number">%SUBMITTED%</span>
                        <span class="stat-label">تم التقديم</span>
                    </div>
                    <div class="stat-box">
                        <span class="stat-number">%INACTIVE%</span>
                        <span class="stat-label">غير نشطين</span>
                    </div>
                </div>
                
                <div class="last-update">
                    آخر تحديث: <span id="update-time">%UPDATE_TIME%</span>
                </div>
                
                <a href="javascript:location.reload()" class="auto-refresh">
                    🔄 تحديث الآن
                </a>
            </header>
            
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>معرف الجهاز</th>
                            <th>اسم الامتحان</th>
                            <th>السؤال الحالي</th>
                            <th>عدد الإجابات</th>
                            <th>الوقت المتبقي</th>
                            <th>الحالة</th>
                            <th>آخر تحديث</th>
                            <th>الموقع</th>
                        </tr>
                    </thead>
                    <tbody>
                        %STUDENTS_ROWS%
                    </tbody>
                </table>
            </div>
            
            <footer>
                <p>📊 نظام تتبع الامتحانات | الإصدار 2.0 | يعمل على: %SERVER_URL%</p>
                <p>🔄 يتم التحديث تلقائياً كل 30 ثانية</p>
            </footer>
        </div>
        
        <script>
            // تحديث الإحصائيات
            function updateStats() {
                const now = new Date();
                document.getElementById('update-time').textContent = 
                    now.toLocaleTimeString('ar-SA');
                
                // تحديث عدادات الحالة
                let active = 0, submitted = 0, inactive = 0;
                document.querySelectorAll('.status-active, .status-inactive, .status-submitted').forEach(el => {
                    if (el.classList.contains('status-active')) active++;
                    else if (el.classList.contains('status-submitted')) submitted++;
                    else inactive++;
                });
                
                document.getElementById('active-count').textContent = active;
            }
            
            // تحديث تلقائي كل 30 ثانية
            setTimeout(() => location.reload(), 30000);
            
            // تحديث وقت التحديث كل دقيقة
            setInterval(updateStats, 60000);
            
            // تحديث أولي
            updateStats();
        </script>
    </body>
    </html>
    """
    
    # بناء صفوف الجدول
    rows = []
    for idx, (device_id, data) in enumerate(sorted_students, 1):
        # تحديد الحالة
        last_update = data.get('last_update', '')
        try:
            update_time = datetime.fromisoformat(last_update)
            time_diff = (now - update_time).seconds
            if data.get('status') == 'submitted':
                status = '<span class="status-submitted">✅ تم التقديم</span>'
            elif time_diff < 120:  # 2 دقائق
                status = '<span class="status-active">🟢 نشط</span>'
            else:
                status = '<span class="status-inactive">🟡 غير نشط</span>'
        except:
            status = '<span class="status-inactive">⚪ غير معروف</span>'
        
        # بناء الصف
        row = f"""
        <tr>
            <td>{idx}</td>
            <td><span class="device-id">{device_id}</span></td>
            <td><strong>{data.get('quiz', 'غير معروف')[:40]}</strong></td>
            <td>{data.get('slide', '?')}</td>
            <td>{data.get('answers_count', 0)}</td>
            <td>{data.get('time_left', '?')} ث</td>
            <td>{status}</td>
            <td>{last_update[:19].replace('T', ' ')}</td>
            <td>{data.get('city', '?')}, {data.get('country', '?')}</td>
        </tr>
        """
        rows.append(row)
    
    # إحصائيات
    total = len(active_students)
    active = sum(1 for d in active_students.values() 
                if d.get('status') == 'active' or 
                (datetime.utcnow() - datetime.fromisoformat(d.get('last_update', '2000-01-01'))).seconds < 120)
    submitted = sum(1 for d in active_students.values() if d.get('status') == 'submitted')
    inactive = total - active - submitted
    
    # استبدال العناصر النائبة
    html = html.replace('%TOTAL%', str(total))
    html = html.replace('%ACTIVE%', str(active))
    html = html.replace('%SUBMITTED%', str(submitted))
    html = html.replace('%INACTIVE%', str(inactive))
    html = html.replace('%UPDATE_TIME%', datetime.utcnow().strftime('%H:%M:%S'))
    html = html.replace('%STUDENTS_ROWS%', ''.join(rows))
    html = html.replace('%SERVER_URL%', request.host_url)
    
    return html

@app.route('/api/students', methods=['GET'])
def api_students():
    """API لجلب بيانات الطلاب"""
    # تنظيف القائمة
    active_students = {}
    now = datetime.utcnow()
    
    for device_id, data in students.items():
        last_update = data.get('last_update')
        if last_update:
            try:
                update_time = datetime.fromisoformat(last_update)
                if (now - update_time).seconds < 600:  # 10 دقائق
                    active_students[device_id] = data
            except:
                pass
    
    return jsonify(list(active_students.values()))

@app.route('/api/stats', methods=['GET'])
def api_stats():
    """API لجلب الإحصائيات"""
    total = len(students)
    
    # حساب النشطين
    now = datetime.utcnow()
    active = 0
    submitted = 0
    
    for data in students.values():
        last_update = data.get('last_update')
        if last_update:
            try:
                update_time = datetime.fromisoformat(last_update)
                if data.get('status') == 'submitted':
                    submitted += 1
                elif (now - update_time).seconds < 120:
                    active += 1
            except:
                pass
    
    inactive = total - active - submitted
    
    return jsonify({
        "total_students": total,
        "active_students": active,
        "submitted_students": submitted,
        "inactive_students": inactive,
        "server_time": now.isoformat(),
        "uptime": "running"
    })

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 نظام تتبع الامتحانات يعمل!")
    print("=" * 60)
    print(f"📊 صفحة العرض: http://localhost:5000/view")
    print(f"📡 endpoint التتبع: http://localhost:5000/")
    print(f"⚡ endpoint الأوامر: http://localhost:5000/commands")
    print("=" * 60)
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
