"""
LAN Chat - 局域网聊天工具
自动发现 · 无需口令 · 本地日志
"""

import socket
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox
import os
import sys
import datetime
import json
import time
import logging
import ipaddress

PORT = 9527
BUFFER = 65536
MAX_IMG_SIZE = 5 * 1024 * 1024

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(get_base_dir(), "lan_chat.log")
HISTORY_FILE = os.path.join(get_base_dir(), "lan_chat_history.json")
IMG_DIR = os.path.join(get_base_dir(), "chat_images")
CONFIG_FILE = os.path.join(get_base_dir(), "lan_chat_config.json")

logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logging.info("="*40)
logging.info("LAN Chat 启动")


def recv_n(sock, n, timeout=3):
    """接收精确 n 字节，超时返回 None"""
    sock.settimeout(timeout)
    buf = b""
    try:
        while len(buf) < n:
            c = sock.recv(n - len(buf))
            if not c:
                return None
            buf += c
    except:
        return None
    finally:
        try:
            sock.settimeout(None)
        except:
            pass
    return buf


def scan_subnet():
    """扫描当前网段内开放 9527 端口的机器"""
    results = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except:
        return results

    parts = ip.split(".")
    base = f"{parts[0]}.{parts[1]}.{parts[2]}."
    logging.info(f"开始扫描网段 {base}0/24")

    def check(host):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect((host, PORT))
            s.close()
            return host
        except:
            return None

    threads = []
    found = []
    lock = threading.Lock()

    def worker(host):
        r = check(host)
        if r:
            with lock:
                found.append(r)

    for i in range(1, 255):
        t = threading.Thread(target=worker, args=(f"{base}{i}",), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=1)

    logging.info(f"扫描完成，发现 {len(found)} 台机器")
    return found


# ====================================================================

class LanChat:
    def __init__(self, root):
        self.root = root
        self.root.title("LAN Chat")
        self.root.geometry("700x620")
        self.root.minsize(620, 540)

        self.sock = None
        self.clients = {}      # {sock: name}
        self.running = False
        self.is_server = False
        self.nickname = os.getlogin()
        self.history = []
        self.lock = threading.Lock()
        self.img_counter = 0
        self._images = []
        self._last_img_path = None
        self._scanned_ips = []

        os.makedirs(IMG_DIR, exist_ok=True)
        self.load_history()
        self.load_config()

        # ===== 顶栏 =====
        top = tk.Frame(root)
        top.pack(fill="x", padx=8, pady=4)

        tk.Label(top, text="昵称:").pack(side="left")
        self.name_entry = tk.Entry(top, width=10)
        self.name_entry.pack(side="left", padx=(2, 6))
        self.name_entry.insert(0, self.nickname)

        self.start_btn = tk.Button(top, text="🚀 启动",
            command=self.toggle_connect, bg="#4CAF50", fg="white", font=("", 9, "bold"))
        self.start_btn.pack(side="right", padx=2)

        self.scan_btn = tk.Button(top, text="🔍 扫描局域网",
            command=self.start_scan, font=("", 9))
        self.scan_btn.pack(side="right", padx=2)

        # ===== 状态 + IP 列表 =====
        info = tk.Frame(root)
        info.pack(fill="x", padx=8)

        self.status_label = tk.Label(info, text="状态: 就绪", fg="#888",
            anchor="w", font=("Consolas", 9))
        self.status_label.pack(side="left")

        self.online_label = tk.Label(info, text="👥 0人", fg="#888")
        self.online_label.pack(side="right")

        # ===== IP 列表 =====
        ip_frame = tk.Frame(root)
        ip_frame.pack(fill="x", padx=8, pady=(2, 0))

        tk.Label(ip_frame, text="局域网在线:", font=("", 9)).pack(side="left")
        self.ip_listbox = tk.Listbox(ip_frame, height=3, font=("Consolas", 9))
        self.ip_listbox.pack(fill="x", side="left", expand=True, padx=(4, 0))
        self.ip_listbox.bind("<Double-Button-1>", self.on_ip_double_click)

        ip_scroll = tk.Scrollbar(ip_frame, orient="vertical", command=self.ip_listbox.yview)
        ip_scroll.pack(side="right", fill="y")
        self.ip_listbox.configure(yscrollcommand=ip_scroll.set)

        # ===== 聊天区（可拖拽） =====
        self.pw = tk.PanedWindow(root, orient=tk.VERTICAL, sashwidth=6,
                                  sashrelief=tk.RAISED, bg="#333")
        self.pw.pack(fill="both", padx=8, pady=(2, 2), expand=True)

        top_frame = tk.Frame(self.pw)
        self.msg_area = scrolledtext.ScrolledText(top_frame, state="disabled",
            height=16, font=("Microsoft YaHei", 10), wrap=tk.WORD)
        self.msg_area.pack(fill="both", expand=True)
        self.msg_area.bind("<Control-v>", self.on_paste_img)
        self.msg_area.bind("<Button-3>", self.on_msg_right_click)
        self.msg_menu = tk.Menu(self.root, tearoff=0)
        self.msg_menu.add_command(label="💾 存为表情包", command=self.save_img_as_sticker)
        self.pw.add(top_frame, height=350)

        bottom_frame = tk.Frame(self.pw)
        self.msg_entry = tk.Text(bottom_frame, height=4, font=("Microsoft YaHei", 10))
        self.msg_entry.pack(fill="both", expand=True)
        self.msg_entry.bind("<Return>", lambda e: self.send_msg() or "break")
        self.msg_entry.bind("<Shift-Return>", lambda e: None)
        self.pw.add(bottom_frame, height=100)

        # ===== 在线用户 =====
        self.user_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.user_var, fg="#888",
            anchor="w", font=("", 9)).pack(fill="x", padx=8)

        # ===== 快捷表情 =====
        emoji_list = ["😂","😅","😏","😎","😭","😡","🥴","🤔","👍","🔥","💀","🎉","🦞"]
        emo_frame = tk.Frame(root)
        emo_frame.pack(fill="x", padx=8, pady=(0, 2))
        for e in emoji_list:
            btn = tk.Button(emo_frame, text=e, font=("", 13), width=2, bd=0,
                command=lambda em=e: self.insert_emoji(em))
            btn.pack(side="left", padx=1)
        tk.Button(emo_frame, text="🖼️ 发图", font=("", 11), bd=1, relief=tk.RAISED,
            command=self.send_image_dialog).pack(side="left", padx=4)
        tk.Button(emo_frame, text="📦 表情包", font=("", 11), bd=1, relief=tk.RAISED,
            command=self.open_sticker_picker).pack(side="left", padx=2)
        self.send_btn = tk.Button(emo_frame, text="发送", command=self.send_msg,
            state="disabled", font=("", 9, "bold"), bg="#2196F3", fg="white", padx=12)
        self.send_btn.pack(side="right", padx=4)

        # ===== 状态栏 =====
        self.status_bar = tk.Label(root, text="💡 启动后自动建群，扫描可发现同一网段的其他用户",
            fg="#666", anchor="w", font=("", 9))
        self.status_bar.pack(fill="x", padx=8, pady=(0, 4))

        self.log("⚡ LAN Chat 已启动")
        if self.history:
            self._show_history()

    # ==================== UI ====================
    def log(self, msg, save=True):
        self.msg_area.config(state="normal")
        self.msg_area.insert(tk.END, msg + "\n")
        self.msg_area.see(tk.END)
        self.msg_area.config(state="disabled")
        if save:
            self.save_history(msg)

    def show_msg(self, sender, content):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {sender}: {content}"
        self.log(line)

    def set_status(self, text, color="#666"):
        self.status_label.config(text=text, fg=color)

    def insert_emoji(self, em):
        self.msg_entry.insert(tk.END, em)
        self.msg_entry.focus()

    # ==================== 历史 ====================
    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    self.history = json.load(f)
            except:
                self.history = []

    def save_history(self, line):
        self.history.append({"t": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "m": line})
        if len(self.history) > 500:
            self.history = self.history[-300:]
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(self.history, f, ensure_ascii=False)
        except:
            pass

    def _show_history(self):
        self.msg_area.config(state="normal")
        self.msg_area.insert(tk.END, f"── 历史记录（共{len(self.history)}条）──\n")
        for h in self.history[-30:]:
            self.msg_area.insert(tk.END, h["m"] + "\n")
        self.msg_area.see(tk.END)
        self.msg_area.config(state="disabled")
        self.log(f"📂 加载了 {len(self.history)} 条历史记录", save=False)

    # ==================== 配置记忆 ====================
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    c = json.load(f)
                self.name_entry.delete(0, tk.END)
                self.name_entry.insert(0, c.get("nickname", self.nickname))
            except:
                pass

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({"nickname": self.name_entry.get().strip() or self.nickname}, f)
        except:
            pass

    # ==================== 扫描 ====================
    def start_scan(self):
        self.scan_btn.config(state="disabled", text="⏳ 扫描中...")
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        logging.info("开始扫描局域网...")
        ips = scan_subnet()
        self._scanned_ips = ips
        self.root.after(0, self._update_ip_list)
        self.root.after(0, lambda: self.scan_btn.config(state="normal", text="🔍 扫描局域网"))
        if ips:
            self.root.after(0, lambda: self.log(f"🔍 发现 {len(ips)} 台机器运行了 LAN Chat"))
        else:
            self.root.after(0, lambda: self.log("🔍 未发现其他 LAN Chat 用户"))

    def _update_ip_list(self):
        self.ip_listbox.delete(0, tk.END)
        for ip in self._scanned_ips:
            self.ip_listbox.insert(tk.END, ip)

    def on_ip_double_click(self, event):
        sel = self.ip_listbox.curselection()
        if not sel:
            return
        ip = self.ip_listbox.get(sel[0])
        if self.running:
            self.log("⚠️ 请先断开当前连接")
            return
        self.nickname = self.name_entry.get().strip() or self.nickname
        self.name_entry.config(state="readonly")
        self.start_btn.config(state="disabled")
        threading.Thread(target=self._start_client, args=(ip,), daemon=True).start()

    # ==================== 连接/断开 ====================
    def toggle_connect(self):
        if self.running:
            self._disconnect()
            return
        self.nickname = self.name_entry.get().strip() or self.nickname
        logging.info(f"启动服务 昵称:{self.nickname}")
        self.save_config()
        self.name_entry.config(state="readonly")
        self.start_btn.config(state="disabled")
        threading.Thread(target=self._start_server, daemon=True).start()

    # ==================== 服务端 ====================
    def _start_server(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", PORT))
            sock.listen(10)
            sock.settimeout(1)
            self.sock = sock
            self.running = True
            self.is_server = True

            with self.lock:
                self.clients[sock] = self.nickname

            local_ip = self.get_local_ip()
            self.root.after(0, lambda: self.status_label.config(
                text=f"🟢 已启动端口 {PORT}  IP:{local_ip}", fg="green"))
            self.root.after(0, lambda: self.start_btn.config(
                text="⏹ 关闭", bg="#f44336", state="normal"))
            self.root.after(0, lambda: self.send_btn.config(state="normal"))
            self.root.after(0, lambda: self.set_status(f"🟢 服务已启动 · 端口 {PORT}"))
            self.root.after(0, lambda: self.log(f"🟢 服务已启动，IP: {local_ip}  端口: {PORT}"))
            self.root.after(0, self._update_user_list)
            self.root.after(0, lambda: self.scan_btn.config(text="🔍 刷新"))

            logging.info(f"服务端启动成功 {local_ip}:{PORT}")

            while self.running:
                try:
                    client, addr = sock.accept()
                    threading.Thread(target=self._handle_client,
                        args=(client, addr), daemon=True).start()
                except socket.timeout:
                    continue
                except:
                    break

        except Exception as e:
            logging.error(f"服务端错误: {e}")
            self.root.after(0, lambda: messagebox.showerror("错误", f"启动失败: {e}"))
            self._disconnect()

    def _handle_client(self, client, addr):
        client.settimeout(5)
        try:
            # 接收昵称
            data = recv_n(client, 4)
            if data is None or data.decode() != "NICK":
                client.close()
                return
            name_len = int(recv_n(client, 4).decode().strip())
            name = recv_n(client, name_len).decode()
            client.sendall(b"OK")

            with self.lock:
                self.clients[client] = name
            logging.info(f"客户端加入: {name} ({addr[0]})")
            self.root.after(0, lambda: self.log(f"🔗 {name} ({addr[0]}) 加入了群聊"))
            self.root.after(0, self._update_user_list)
            self._broadcast(f"💬 {name} 加入了群聊", exclude=client)

            # 消息循环
            while self.running:
                hdr = recv_n(client, 4)
                if hdr is None:
                    break
                t = hdr.decode()
                if t == "MSG:":
                    sz = int(recv_n(client, 8).decode().strip())
                    body = recv_n(client, sz)
                    if body is None:
                        break
                    text = body.decode()
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    self.root.after(0, lambda n=name, c=text: self.show_msg(n, c))
                    self._broadcast_raw(f"MSG:{name}:{text}", exclude=client)

                elif t == "IMG:":
                    sz = int(recv_n(client, 8).decode().strip())
                    remain = sz
                    chunks = []
                    while remain > 0:
                        ck = recv_n(client, min(BUFFER, remain))
                        if ck is None:
                            break
                        chunks.append(ck)
                        remain -= len(ck)
                    img = b"".join(chunks)
                    self._handle_image_data(name, img)
                    self._broadcast_raw(
                        f"IMG:{name}:{sz}:".encode() + img, exclude=client)
                else:
                    break

        except:
            pass

        finally:
            with self.lock:
                if client in self.clients:
                    nm = self.clients.pop(client)
                    logging.info(f"客户端离开: {nm}")
                    self.root.after(0, lambda n=nm: self.log(f"🔌 {n} 离开了群聊"))
                    self.root.after(0, self._update_user_list)
                    self._broadcast(f"💬 {nm} 离开了群聊")
            try:
                client.close()
            except:
                pass

    # ==================== 客户端 ====================
    def _start_client(self, ip):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, PORT))
            sock.settimeout(None)
            self.sock = sock
            self.running = True
            self.is_server = False

            self.root.after(0, lambda: self.status_label.config(text=f"🟢 已连接 {ip}", fg="green"))
            self.root.after(0, lambda: self.start_btn.config(
                text="⏹ 断开", bg="#f44336", state="normal"))
            self.root.after(0, lambda: self.send_btn.config(state="normal"))
            self.root.after(0, lambda: self.set_status(f"🟢 已连接 {ip}:{PORT}"))
            self.root.after(0, lambda: self.log(f"🔗 正在连接 {ip}:{PORT}..."))

            # 发送昵称
            name_b = self.nickname.encode()
            sock.sendall(b"NICK" + f"{len(name_b):<4}".encode() + name_b)
            if recv_n(sock, 2) is None:
                raise Exception("服务端未确认")
            self.root.after(0, lambda: self.log("✅ 已加入群聊"))

            while self.running:
                hdr = recv_n(sock, 4)
                if hdr is None:
                    break
                t = hdr.decode()
                if t == "MSG:":
                    sz = int(recv_n(sock, 8).decode().strip())
                    body = recv_n(sock, sz)
                    if body is None:
                        break
                    text = body.decode()
                    if ":" in text:
                        s, m = text.split(":", 1)
                        self.root.after(0, lambda s=s.strip(), m=m.strip(): self.show_msg(s, m))
                    else:
                        self.root.after(0, lambda c=text: self.log(f"💬 {c}"))
                elif t == "IMG:":
                    sz = int(recv_n(sock, 8).decode().strip())
                    remain = sz
                    chunks = []
                    while remain > 0:
                        ck = recv_n(sock, min(BUFFER, remain))
                        if ck is None:
                            break
                        chunks.append(ck)
                        remain -= len(ck)
                    img = b"".join(chunks)
                    self._handle_image_data("未知", img)

        except socket.timeout:
            self.root.after(0, lambda: messagebox.showerror("错误", "连接超时"))
        except ConnectionRefusedError:
            self.root.after(0, lambda: messagebox.showerror("错误", "连接被拒绝"))
        except Exception as e:
            logging.error(f"客户端连接失败: {e}")
            self.root.after(0, lambda: self.log(f"❌ 连接失败: {e}"))

        self.root.after(0, lambda: self.log("🔌 已断开"))
        self._disconnect()

    # ==================== 广播 ====================
    def _broadcast(self, msg, exclude=None):
        raw = f"{self.nickname}:{msg}"
        with self.lock:
            for s in list(self.clients.keys()):
                if s == exclude or s == self.sock:
                    continue
                try:
                    body = raw.encode()
                    s.sendall(b"MSG:" + f"{len(body):<8}".encode() + body)
                except:
                    pass

    def _broadcast_raw(self, raw_binary, exclude=None):
        with self.lock:
            for s in list(self.clients.keys()):
                if s == exclude or s == self.sock:
                    continue
                try:
                    if isinstance(raw_binary, str):
                        raw_binary = raw_binary.encode()
                    s.sendall(raw_binary)
                except:
                    pass

    def _update_user_list(self):
        names = [self.nickname]
        with self.lock:
            for _, n in self.clients.items():
                if n not in names:
                    names.append(n)
        self.user_var.set(f"👥 在线: {' · '.join(names)}")
        self.online_label.config(text=f"👥 {len(names)}人")

    # ==================== 发送 ====================
    def send_msg(self):
        text = self.msg_entry.get("1.0", tk.END).strip()
        if not text or not self.running:
            return
        self.msg_entry.delete("1.0", tk.END)
        self.show_msg(self.nickname, text)

        if self.is_server:
            self._broadcast(text)
        else:
            try:
                body = f"{self.nickname}:{text}".encode()
                self.sock.sendall(b"MSG:" + f"{len(body):<8}".encode() + body)
            except:
                self.log("❌ 发送失败")
                self._disconnect()

    # ==================== 图片 ====================
    def send_image_dialog(self):
        if not self.running:
            messagebox.showwarning("提示", "请先加入群聊")
            return
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.bmp"), ("所有", "*.*")])
        if not path:
            return
        if os.path.getsize(path) > MAX_IMG_SIZE:
            messagebox.showerror("错误", f"图片太大，最大5MB")
            return
        self._send_image_file(path)

    def on_paste_img(self, event):
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img:
                path = os.path.join(IMG_DIR, f"paste_{int(time.time())}.png")
                img.save(path)
                self._send_image_file(path)
                return "break"
        except:
            pass

    def _send_image_file(self, path):
        try:
            with open(path, "rb") as f:
                img_bytes = f.read()
            ext = os.path.splitext(path)[1].lower()
            self.img_counter += 1
            fname = f"sent_{int(time.time())}_{self.img_counter}{ext}"
            fpath = os.path.join(IMG_DIR, fname)
            with open(fpath, "wb") as f:
                f.write(img_bytes)
            self._process_and_show_image(self.nickname, fpath)

            payload = b"IMG:" + f"{len(img_bytes):<8}".encode() + img_bytes
            if self.is_server:
                self._broadcast_raw(payload)
            else:
                self.sock.sendall(payload)
        except Exception as e:
            self.log(f"❌ 图片发送失败: {e}")

    def _handle_image_data(self, sender, img_bytes):
        if len(img_bytes) > MAX_IMG_SIZE:
            return
        try:
            self.img_counter += 1
            fname = f"img_{int(time.time())}_{self.img_counter}.png"
            fpath = os.path.join(IMG_DIR, fname)
            with open(fpath, "wb") as f:
                f.write(img_bytes)
            threading.Thread(target=self._process_and_show_image,
                args=(sender, fpath), daemon=True).start()
        except:
            pass

    def _process_and_show_image(self, sender, fpath):
        try:
            from PIL import Image, ImageTk
            img = Image.open(fpath)
            w, h = img.size
            if w > 200:
                h = int(h * 200 / w)
                w = 200
            img = img.resize((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.root.after(0, lambda: self._display_image(sender, fpath, photo))
        except ImportError:
            self.root.after(0, lambda: self.log(
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {sender}: [图片]"))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"❌ 图片处理失败: {e}"))

    def _display_image(self, sender, fpath, photo):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.msg_area.config(state="normal")
        self.msg_area.insert(tk.END, f"[{ts}] {sender}: [图片]\n")
        self.msg_area.image_create(tk.END, image=photo)
        self.msg_area.insert(tk.END, "\n")
        self.msg_area.see(tk.END)
        self.msg_area.config(state="disabled")
        self._images.append(photo)
        self._last_img_path = fpath

    # ==================== 表情包 ====================
    def open_sticker_picker(self):
        STICKER_DIR = os.path.join(get_base_dir(), "stickers")
        os.makedirs(STICKER_DIR, exist_ok=True)
        files = sorted(os.listdir(STICKER_DIR), reverse=True)
        if not files:
            self.log("💡 还没表情包，在图片上右键→「存为表情包」添加")
            return
        win = tk.Toplevel(self.root)
        win.title("表情包")
        win.geometry("520x400")
        canvas = tk.Canvas(win, bg="#f0f0f0")
        scroll = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas, bg="#f0f0f0")
        frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        row = col = 0
        for fname in files:
            fpath = os.path.join(STICKER_DIR, fname)
            try:
                from PIL import Image, ImageTk
                img = Image.open(fpath)
                img.thumbnail((80, 80), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                btn = tk.Button(frame, image=photo, bd=1, relief=tk.RAISED,
                    command=lambda p=fpath: self.send_sticker(p))
                btn.image = photo
                btn.grid(row=row, column=col, padx=4, pady=4)
                col += 1
                if col > 4:
                    col = 0
                    row += 1
            except:
                continue

    def send_sticker(self, fpath):
        if not self.running:
            return
        self._send_image_file(fpath)

    def on_msg_right_click(self, event):
        if self._last_img_path and os.path.exists(self._last_img_path):
            self.msg_menu.tk_popup(event.x_root, event.y_root)

    def save_img_as_sticker(self):
        if not self._last_img_path or not os.path.exists(self._last_img_path):
            self.log("❌ 没有可保存的图片")
            return
        dst = os.path.join(get_base_dir(), "stickers", f"sticker_{int(time.time())}.png")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            from PIL import Image
            Image.open(self._last_img_path).save(dst)
            self.log(f"✅ 已保存表情包")
        except Exception as e:
            self.log(f"❌ 保存失败: {e}")

    # ==================== 断开 ====================
    def _disconnect(self):
        logging.info("断开连接")
        self.running = False
        self.is_server = False
        with self.lock:
            for s in list(self.clients.keys()):
                try:
                    s.close()
                except:
                    pass
            self.clients.clear()
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.sock = None
        self.root.after(0, lambda: self.start_btn.config(
            text="🚀 启动", bg="#4CAF50", state="normal"))
        self.root.after(0, lambda: self.send_btn.config(state="disabled"))
        self.root.after(0, lambda: self.status_label.config(text="状态: 就绪", fg="#888"))
        self.root.after(0, lambda: self.user_var.set(""))
        self.root.after(0, lambda: self.online_label.config(text="👥 0人"))
        self.root.after(0, lambda: self.set_status("⏹ 已断开"))
        try:
            self.name_entry.config(state="normal")
        except:
            pass

    @staticmethod
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"


if __name__ == "__main__":
    root = tk.Tk()
    app = LanChat(root)
    root.mainloop()
