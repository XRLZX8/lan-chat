"""
LAN Chat v3 - P2P 局域网聊天
无需口令 · 自动发现 · 自动连接 · 网状网络
"""

import socket, threading, tkinter as tk, os, sys, datetime, json, time, logging
from tkinter import scrolledtext, messagebox
from concurrent.futures import ThreadPoolExecutor

PORT = 9527
BUFFER = 65536
MAX_IMG_SIZE = 1024 * 1024  # 1MB

def BASE():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(filename=os.path.join(BASE(), "lan_chat.log"),
    level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S")
logging.info("="*40 + "\nLAN Chat v3 启动")


def recv_n(sock, n, timeout=None):
    """接收精确 n 字节。timeout=None 表示阻塞等待（用于等待下一条消息）"""
    sock.settimeout(timeout)
    buf = b""
    try:
        while len(buf) < n:
            c = sock.recv(n - len(buf))
            if not c: return None
            buf += c
    except: return None
    finally:
        try: sock.settimeout(None)
        except: pass
    return buf


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"


def scan_subnet():
    ip = get_local_ip()
    base = ".".join(ip.split(".")[:3]) + "."
    found = []
    lock = threading.Lock()

    def check(h):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect((h, PORT))
            s.close()
            with lock: found.append(h)
        except: pass

    threads = [threading.Thread(target=check, args=(f"{base}{i}",), daemon=True)
               for i in range(1, 255)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=1.5)
    return found


class LanChat:
    def __init__(self, root):
        self.root = root
        self.root.title("LAN Chat")
        self.root.geometry("720x640")
        self.root.minsize(620, 540)

        self.server = None          # 服务端 socket
        self.peers = {}             # {sock: {"name":name, "ip":ip}}
        self.my_name = os.getlogin()
        self.running = False
        self.history = []
        self.lock = threading.Lock()
        self._images = []
        self._last_img = None
        self._img_executor = ThreadPoolExecutor(max_workers=2)

        os.makedirs(os.path.join(BASE(), "chat_images"), exist_ok=True)
        self._load_history()

        # === UI ===
        top = tk.Frame(root); top.pack(fill="x", padx=8, pady=4)
        tk.Label(top, text="昵称:").pack(side="left")
        self.name_et = tk.Entry(top, width=12)
        self.name_et.pack(side="left", padx=2)
        self.name_et.insert(0, self.my_name)
        self.start_btn = tk.Button(top, text="🚀 启动聊天",
            command=self.toggle, bg="#4CAF50", fg="white", font=("", 9, "bold"))
        self.start_btn.pack(side="right")
        tk.Label(top, text="  自动发现并连接同一网段用户", fg="#888", font=("", 8)).pack(side="right")

        info = tk.Frame(root); info.pack(fill="x", padx=8)
        self.st = tk.Label(info, text="状态: 就绪", fg="#888", anchor="w", font=("Consolas", 9))
        self.st.pack(side="left")
        self.online_lb = tk.Label(info, text="👥 0人", fg="#888")
        self.online_lb.pack(side="right")

        # 在线用户持久显示（聊天区上方）
        self.ulb = tk.Label(root, text="", fg="#58a6ff", anchor="w",
            font=("Consolas", 9), justify="left", bg="#10141a",
            padx=6, pady=4)
        self.ulb.pack(fill="x", padx=8, pady=(2, 0))

        # 聊天区（可拖拽）
        self.pw = tk.PanedWindow(root, orient=tk.VERTICAL, sashwidth=6,
                                  sashrelief=tk.RAISED, bg="#333")
        self.pw.pack(fill="both", padx=8, pady=(2, 2), expand=True)
        tf = tk.Frame(self.pw)
        self.msg = scrolledtext.ScrolledText(tf, state="disabled",
            font=("Microsoft YaHei", 10), wrap=tk.WORD)
        self.msg.pack(fill="both", expand=True)
        self.msg.bind("<Button-3>", self.on_msg_right_click)
        self.msg_menu = tk.Menu(self.root, tearoff=0)
        self.msg_menu.add_command(label="💾 存为表情包", command=self.save_img_as_sticker)
        self.pw.add(tf, height=350)
        bf = tk.Frame(self.pw)
        self.input = tk.Text(bf, height=4, font=("Microsoft YaHei", 10))
        self.input.pack(fill="both", expand=True)
        self.input.bind("<Return>", lambda e: self.send() or "break")
        self.input.bind("<Shift-Return>", lambda e: None)
        self.pw.add(bf, height=100)

        emo = tk.Frame(root); emo.pack(fill="x", padx=8, pady=(0, 2))
        for e in "😂😅😏😎😭😡👍🔥💀🎉🦞":
            tk.Button(emo, text=e, font=("", 13), width=2, bd=0,
                command=lambda em=e: self._ins(em)).pack(side="left")
        tk.Button(emo, text="🖼️ 发图", font=("", 11), bd=1, relief=tk.RAISED,
            command=self._pick_img).pack(side="left", padx=4)
        tk.Button(emo, text="📦 表情包", font=("", 11), bd=1, relief=tk.RAISED,
            command=self.open_sticker_picker).pack(side="left", padx=2)
        self.sbtn = tk.Button(emo, text="发送", command=self.send,
            state="disabled", font=("", 9, "bold"), bg="#2196F3", fg="white")
        self.sbtn.pack(side="right", padx=4)

        self.sb = tk.Label(root, text="💡 启动后自动建群+发现并连接同网段用户",
            fg="#666", anchor="w", font=("", 9))
        self.sb.pack(fill="x", padx=8, pady=(0, 4))

        self.log("⚡ LAN Chat v3 已启动")
        if self.history:
            self.msg.config(state="normal")
            self.msg.insert(tk.END, f"── 历史({len(self.history)}条)──\n")
            for h in self.history[-30:]:
                self.msg.insert(tk.END, h["m"] + "\n")
            self.msg.see(tk.END)
            self.msg.config(state="disabled")
            self.log(f"📂 加载 {len(self.history)} 条记录", False)

    def _ins(self, e):
        self.input.insert(tk.END, e); self.input.focus()

    def log(self, msg, sv=True):
        self.msg.config(state="normal")
        self.msg.insert(tk.END, msg + "\n")
        self.msg.see(tk.END)
        self.msg.config(state="disabled")
        if sv: self._save(msg)

    def msg_in(self, sender, text):
        t = datetime.datetime.now().strftime("%H:%M:%S")
        self.log(f"[{t}] {sender}: {text}")

    def _load_history(self):
        p = os.path.join(BASE(), "lan_chat_history.json")
        if os.path.exists(p):
            try: self.history = json.load(open(p))
            except: self.history = []

    def _save(self, line):
        self.history.append({"t": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "m": line})
        if len(self.history) > 500: self.history = self.history[-300:]
        try: json.dump(self.history, open(os.path.join(BASE(), "lan_chat_history.json"), "w"), ensure_ascii=False)
        except: pass

    def _upd_users(self):
        my_ip = get_local_ip()
        n = len(self.peers) + 1
        lines = [f"👥 在线 {n} 人"]
        lines.append(f"  📍 {self.my_name} (我) {my_ip}")
        with self.lock:
            for p in self.peers.values():
                lines.append(f"  👤 {p['name']} ({p['ip']})")
        self.ulb.config(text="\n".join(lines))
        self.online_lb.config(text=f"👥 {n}人")
        # 底部状态栏实时描述
        if self.running:
            if n <= 1:
                self.sb.config(text="🟢 仅你一人，等待其他人启动聊天...")
            else:
                self.sb.config(text=f"🟢 在线 {n} 人，可畅聊")

    # ==================== 主开关 ====================
    def toggle(self):
        if self.running: self._stop(); return
        self.my_name = self.name_et.get().strip() or self.my_name
        logging.info(f"启动 昵称:{self.my_name}")
        self.name_et.config(state="readonly")
        self.start_btn.config(state="disabled", text="⏳ 启动中...")
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self):
        # 1. 启动服务端
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", PORT))
            s.listen(10); s.settimeout(1)
            self.server = s
            self.running = True
            ip = get_local_ip()
            self.root.after(0, lambda: self.st.config(text=f"🟢 {ip}:{PORT}", fg="green"))
            self.root.after(0, lambda: self.start_btn.config(text="⏹ 关闭", bg="#f44336", state="normal"))
            self.root.after(0, lambda: self.sbtn.config(state="normal"))
            self.root.after(0, lambda: self.sb.config(text=f"🟢 已启动，正在发现其他用户..."))
            self.root.after(0, lambda: self.log(f"🟢 已启动 {ip}:{PORT}"))
            threading.Thread(target=self._accept_loop, daemon=True).start()
        except Exception as e:
            logging.error(f"启动失败: {e}")
            self.root.after(0, lambda: messagebox.showerror("错误", f"端口{PORT}被占用: {e}"))
            self._stop(); return

        # 2. 扫描并自动连接
        peers = scan_subnet()
        my_ip = get_local_ip()
        for p in peers:
            if p == my_ip: continue
            already = any(pd["ip"] == p for pd in self.peers.values())
            if not already:
                self.root.after(0, lambda ip=p: self.log(f"🔍 发现 {ip}，正在连接..."))
                threading.Thread(target=self._connect_to, args=(p,), daemon=True).start()
        cnt = len(peers) - (1 if my_ip in peers else 0)
        self.root.after(0, lambda: self.log(f"🔍 发现 {cnt} 台其他机器" if cnt else "🔍 未发现其他用户"))
        self.root.after(0, lambda: self.sb.config(
            text=f"🟢 在线 {len(self.peers)+1} 人" if cnt else "🟢 仅你一人，等待其他人启动..."))

    # ==================== 服务端 ====================
    def _accept_loop(self):
        while self.running:
            try:
                c, addr = self.server.accept()
                threading.Thread(target=self._handle, args=(c, addr[0]), daemon=True).start()
            except socket.timeout: continue
            except: break

    def _handle(self, c, ip):
        c.settimeout(5)
        try:
            d = recv_n(c, 4, 10)
            if d is None or d.decode() != "NICK": c.close(); return
            nl = int(recv_n(c, 4, 10).decode().strip())
            nm = recv_n(c, nl, 10).decode()
            c.sendall(b"OK")
            # 把自己的名字也发过去，让客户端能显示
            nb = self.my_name.encode()
            c.sendall(f"{len(nb):<4}".encode() + nb)

            # 去重：同一 IP 已有连接则关闭新连接
            with self.lock:
                dup = any(p["ip"] == ip for p in self.peers.values())
                if dup:
                    c.close()
                    return
                self.peers[c] = {"name": nm, "ip": ip}
            self.root.after(0, self._upd_users)

            while self.running:
                h = recv_n(c, 4)  # 阻塞等消息，不超时
                if h is None: break
                t = h.decode()
                if t == "MSG:":
                    sz = int(recv_n(c, 8, 10).decode().strip())
                    b = recv_n(c, sz, 10)
                    if b is None: break
                    txt = b.decode()
                    self.root.after(0, lambda n=nm, x=txt: self.msg_in(n, x))
                    self._bc(f"{nm}:{txt}", c)
                elif t == "IMG:":
                    sz = int(recv_n(c, 8, 10).decode().strip())
                    remain, chk = sz, []
                    while remain > 0:
                        ck = recv_n(c, min(BUFFER, remain), 10)
                        if ck is None: break
                        chk.append(ck); remain -= len(ck)
                    if remain == 0:
                        img = b"".join(chk)
                        self._handle_img(nm, img)
                        self._bc_raw(b"IMG:" + f"{sz:<8}".encode() + img, c)
                else: break
        except: pass
        finally:
            with self.lock:
                if c in self.peers:
                    self.peers.pop(c)
                    self.root.after(0, self._upd_users)
            try: c.close()
            except: pass

    # ==================== 客户端 ====================
    def _connect_to(self, ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((ip, PORT))
            s.settimeout(None)
            # 去重
            with self.lock:
                if any(p["ip"] == ip for p in self.peers.values()):
                    s.close()
                    return
            nb = self.my_name.encode()
            s.sendall(b"NICK" + f"{len(nb):<4}".encode() + nb)
            if recv_n(s, 2, 10) is None:
                s.close(); return
            # 读取服务端的用户名
            nl = int(recv_n(s, 4, 10).decode().strip())
            nm = recv_n(s, nl, 10).decode()
            with self.lock: self.peers[s] = {"name": nm, "ip": ip}
            self.root.after(0, self._upd_users)

            while self.running:
                h = recv_n(s, 4)  # 阻塞等消息
                if h is None: break
                t = h.decode()
                if t == "MSG:":
                    sz = int(recv_n(s, 8, 10).decode().strip())
                    b = recv_n(s, sz, 10)
                    if b is None: break
                    txt = b.decode()
                    if ":" in txt:
                        sn, msg = txt.split(":", 1)
                        self.root.after(0, lambda s=sn.strip(), m=msg.strip(): self.msg_in(s, m))
                    else:
                        self.root.after(0, lambda c=txt: self.log(f"💬 {c}"))
                elif t == "IMG:":
                    sz = int(recv_n(s, 8, 10).decode().strip())
                    remain, chk = sz, []
                    while remain > 0:
                        ck = recv_n(s, min(BUFFER, remain), 10)
                        if ck is None: break
                        chk.append(ck); remain -= len(ck)
                    if remain == 0:
                        self._handle_img(nm, b"".join(chk))
            with self.lock:
                if s in self.peers: self.peers.pop(s)
            self.root.after(0, self._upd_users)
        except: pass
        finally:
            try: s.close()
            except: pass

    # ==================== 广播 ====================
    def _bc(self, msg, exclude=None):
        raw = f"{self.my_name}:{msg}"
        with self.lock:
            for s in list(self.peers.keys()):
                if s == exclude: continue
                try:
                    b = raw.encode()
                    s.sendall(b"MSG:" + f"{len(b):<8}".encode() + b)
                except: pass

    def _bc_raw(self, raw, exclude=None):
        with self.lock:
            for s in list(self.peers.keys()):
                if s == exclude: continue
                try: s.sendall(raw)
                except: pass

    # ==================== 发送 ====================
    def send(self):
        txt = self.input.get("1.0", tk.END).strip()
        if not txt or not self.running: return
        self.input.delete("1.0", tk.END)
        self.msg_in(self.my_name, txt)
        self._bc(txt)

    # ==================== 图片 ====================
    def _pick_img(self):
        if not self.running: messagebox.showwarning("提示", "请先启动"); return
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="选图",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.bmp")])
        if not p: return
        sz = os.path.getsize(p)
        if sz > MAX_IMG_SIZE: messagebox.showerror("错误", "图片超过1MB"); return
        self._send_img(p)

    def _send_img(self, path):
        try:
            with open(path, "rb") as f: data = f.read()
            ext = os.path.splitext(path)[1]
            name = f"sent_{int(time.time())}{ext}"
            fpath = os.path.join(BASE(), "chat_images", name)
            with open(fpath, "wb") as f: f.write(data)
            # 自己发的也要显示缩略图
            self._img_executor.submit(self._proc_img, self.my_name, fpath)
            self._bc_raw(b"IMG:" + f"{len(data):<8}".encode() + data)
        except Exception as e:
            self.log(f"❌ 发送失败: {e}")

    def _handle_img(self, sender, data):
        if len(data) > MAX_IMG_SIZE: return
        try:
            name = f"img_{int(time.time())}.png"
            fpath = os.path.join(BASE(), "chat_images", name)
            with open(fpath, "wb") as f: f.write(data)
            self._img_executor.submit(self._proc_img, sender, fpath)
        except: pass

    def _proc_img(self, sender, fpath):
        try:
            from PIL import Image, ImageTk
            img = Image.open(fpath)
            w, h = img.size
            if w > 200: h, w = int(h*200/w), 200
            img = img.resize((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.root.after(0, lambda: self._show_img(sender, fpath, photo))
        except:
            self.root.after(0, lambda: self.log(
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {sender}: [图片]"))

    def _show_img(self, sender, fpath, photo=None):
        t = datetime.datetime.now().strftime("%H:%M:%S")
        self.msg.config(state="normal")
        self.msg.insert(tk.END, f"[{t}] {sender}: [图片]\n")
        if photo:
            self.msg.image_create(tk.END, image=photo)
            self.msg.insert(tk.END, "\n")
            self._images.append(photo)
        self.msg.see(tk.END)
        self.msg.config(state="disabled")
        self._last_img = fpath

    # ==================== 表情包 ====================
    def open_sticker_picker(self):
        d = os.path.join(BASE(), "stickers")
        os.makedirs(d, exist_ok=True)
        files = sorted(os.listdir(d), reverse=True)
        if not files:
            self.log("💡 还没表情包，在图片上右键→存为表情包添加")
            return
        win = tk.Toplevel(self.root)
        win.title("表情包"); win.geometry("520x400")
        cv = tk.Canvas(win, bg="#f0f0f0")
        sb = tk.Scrollbar(win, orient="vertical", command=cv.yview)
        f = tk.Frame(cv, bg="#f0f0f0")
        f.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=f, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        r = c = 0
        for fn in files:
            fp = os.path.join(d, fn)
            try:
                from PIL import Image, ImageTk
                img = Image.open(fp)
                img.thumbnail((80, 80), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                btn = tk.Button(f, image=photo, bd=1, relief=tk.RAISED,
                    command=lambda p=fp: self.send_sticker(p))
                btn.image = photo
                btn.grid(row=r, column=c, padx=4, pady=4)
                c += 1
                if c > 4: c = 0; r += 1
            except: continue

    def send_sticker(self, fpath):
        if not self.running: return
        self._send_img(fpath)

    def on_msg_right_click(self, event):
        if self._last_img and os.path.exists(self._last_img):
            self.msg_menu.tk_popup(event.x_root, event.y_root)

    def save_img_as_sticker(self):
        if not self._last_img or not os.path.exists(self._last_img):
            self.log("❌ 没有可保存的图片"); return
        dst = os.path.join(BASE(), "stickers", f"sticker_{int(time.time())}.png")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            from PIL import Image
            Image.open(self._last_img).save(dst)
            self.log("✅ 已保存表情包")
        except Exception as e:
            self.log(f"❌ 保存失败: {e}")

    # ==================== 停止 ====================
    def _stop(self):
        logging.info("停止")
        self.running = False
        with self.lock:
            for s in list(self.peers.keys()):
                try: s.close()
                except: pass
            self.peers.clear()
        if self.server:
            try: self.server.close()
            except: pass
            self.server = None
        self.root.after(0, lambda: self.start_btn.config(text="🚀 启动聊天", bg="#4CAF50", state="normal"))
        self.root.after(0, lambda: self.sbtn.config(state="disabled"))
        self.root.after(0, lambda: self.st.config(text="状态: 就绪", fg="#888"))
        self.root.after(0, lambda: self.ulb.config(text=""))
        self.root.after(0, lambda: self.online_lb.config(text="👥 0人"))
        self.root.after(0, lambda: self.sb.config(text="⏹ 已断开"))
        try: self.name_et.config(state="normal")
        except: pass


if __name__ == "__main__":
    root = tk.Tk()
    app = LanChat(root)
    root.mainloop()
