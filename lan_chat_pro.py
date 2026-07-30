"""
LAN Chat Pro - 局域网聊天工具（多人版）
口令认证 · 表情包 · 图片 · 历史记录
"""

import socket
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, filedialog
import hashlib
import os
import sys
import datetime
import json
import base64
import time

PORT = 8888
BUFFER = 65536
MAX_IMG_SIZE = 5 * 1024 * 1024  # 5MB


def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

STICKER_DIR = os.path.join(get_base_dir(), "stickers")
HISTORY_FILE = os.path.join(get_base_dir(), "lan_chat_history.json")
IMG_DIR = os.path.join(get_base_dir(), "chat_images")

QUICK_EMOJIS = ["😂","😅","😏","😎","😭","😡","🥴","🤔","👍","👎","❤️","🔥","💀","🎉","🚀","💪","🫡","🤣","😤","😈","🦞","🐶","🌚","💩"]


def _recv_exact(sock, size, timeout=5):
    """接收精确长度的数据（带超时）"""
    sock.settimeout(timeout)
    buf = b""
    try:
        while len(buf) < size:
            chunk = sock.recv(size - len(buf))
            if not chunk:
                return None
            buf += chunk
    except socket.timeout:
        return None
    except:
        return None
    finally:
        try:
            sock.settimeout(None)
        except:
            pass
    return buf


class LanChatPro:
    def __init__(self, root):
        self.root = root
        self.root.title("LAN Chat Pro")
        self.root.geometry("680x620")
        self.root.minsize(620, 540)

        self.server_sock = None
        self.client_sock = None
        self.clients = {}
        self.running = False
        self.is_server = False
        self.nickname = os.getlogin()
        self.history = []
        self.lock = threading.Lock()
        self.img_counter = 0
        self._images = []
        self._last_img_path = None

        os.makedirs(IMG_DIR, exist_ok=True)
        os.makedirs(STICKER_DIR, exist_ok=True)
        self.load_history()

        # ===== 顶部栏 =====
        top = tk.Frame(root)
        top.pack(fill="x", padx=8, pady=4)

        tk.Label(top, text="昵称:").pack(side="left")
        self.name_entry = tk.Entry(top, width=10)
        self.name_entry.pack(side="left", padx=(2, 6))
        self.name_entry.insert(0, self.nickname)

        self.mode_var = tk.StringVar(value="server")
        tk.Radiobutton(top, text="🏠 建群", variable=self.mode_var,
                       value="server").pack(side="left")
        tk.Radiobutton(top, text="🔗 加群", variable=self.mode_var,
                       value="client").pack(side="left")

        self.connect_btn = tk.Button(top, text="🚀 启动",
                                     command=self.do_connect,
                                     bg="#4CAF50", fg="white",
                                     font=("", 9, "bold"))
        self.connect_btn.pack(side="right", padx=4)

        # ===== 信息栏 =====
        info = tk.Frame(root)
        info.pack(fill="x", padx=8)
        self.ip_label = tk.Label(info, text="状态: 就绪",
                                 fg="#888", anchor="w", font=("Consolas", 9))
        self.ip_label.pack(side="left")
        self.online_label = tk.Label(info, text="👥 0人", fg="#888")
        self.online_label.pack(side="right")

        # ===== 可拖拽分割的主区域 =====
        self.pw = tk.PanedWindow(root, orient=tk.VERTICAL, sashwidth=6,
                                  sashrelief=tk.RAISED, bg="#333")
        self.pw.pack(fill="both", padx=8, pady=(2, 2), expand=True)

        # 上：聊天区
        top_frame = tk.Frame(self.pw)
        self.msg_area = scrolledtext.ScrolledText(
            top_frame, state="disabled", height=18,
            font=("Microsoft YaHei", 10), wrap=tk.WORD)
        self.msg_area.pack(fill="both", expand=True)
        self.msg_area.bind("<Control-v>", self.on_paste_img)
        # 右键菜单
        self.msg_area.bind("<Button-3>", self.on_msg_right_click)
        self.msg_menu = tk.Menu(self.root, tearoff=0)
        self.msg_menu.add_command(label="💾 存为表情包", command=self.save_last_img_as_sticker)
        self.pw.add(top_frame, height=350)

        # 下：输入区
        bottom_frame = tk.Frame(self.pw)
        self.msg_entry = tk.Text(bottom_frame, height=4,
                                 font=("Microsoft YaHei", 10))
        self.msg_entry.pack(fill="both", expand=True, pady=(0, 0))
        self.msg_entry.bind("<Return>", self.on_enter)
        self.msg_entry.bind("<Shift-Return>", lambda e: None)
        self.pw.add(bottom_frame, height=120)

        # ===== 在线用户 =====
        self.user_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.user_var, fg="#888",
                 anchor="w", font=("", 9)).pack(fill="x", padx=8)

        # ===== 快捷表情 + 功能按钮 =====
        emo_frame = tk.Frame(root)
        emo_frame.pack(fill="x", padx=8, pady=(0, 2))
        for e in QUICK_EMOJIS:
            btn = tk.Button(emo_frame, text=e, font=("", 13),
                            width=2, bd=0,
                            command=lambda em=e: self.insert_emoji(em))
            btn.pack(side="left", padx=1)
        tk.Button(emo_frame, text="🖼️ 发图", font=("", 11),
                  bd=1, relief=tk.RAISED, bg="#E8E8E8",
                  command=self.send_image_dialog).pack(side="left", padx=4)
        tk.Button(emo_frame, text="📦 表情包", font=("", 11),
                  bd=1, relief=tk.RAISED, bg="#E8E8E8",
                  command=self.open_sticker_picker).pack(side="left", padx=2)
        self.send_btn = tk.Button(emo_frame, text="发送",
                                  command=self.send_msg,
                                  state="disabled",
                                  font=("", 9, "bold"),
                                  bg="#2196F3", fg="white", padx=12)
        self.send_btn.pack(side="right", padx=4)

        # ===== 状态栏 =====
        self.status_bar = tk.Label(root,
                                   text="💡 建群 = 创建房间 | 加群 = 输入对方IP",
                                   fg="#666", anchor="w", font=("", 9))
        self.status_bar.pack(fill="x", padx=8, pady=(0, 4))

        self.log("⚡ LAN Chat Pro 已启动")
        if self.history:
            self.log(f"📂 加载了 {len(self.history)} 条历史记录")

    # ==================== UI ====================
    def log(self, msg, save=True):
        self.msg_area.config(state="normal")
        self.msg_area.insert(tk.END, msg + "\n")
        self.msg_area.see(tk.END)
        self.msg_area.config(state="disabled")
        if save and not msg.startswith("⚡") and not msg.startswith("💡") \
                and not msg.startswith("📂"):
            self.save_history(msg)

    def show_msg(self, sender, content):
        ts = datetime.datetime.now().strftime("%m-%d %H:%M:%S")
        self.log(f"[{ts}] {sender}: {content}")

    def set_status(self, text, color="#666"):
        self.status_bar.config(text=text, fg=color)

    def insert_emoji(self, em):
        self.msg_entry.insert(tk.END, em)
        self.msg_entry.focus()

    def on_enter(self, event):
        self.send_msg()
        return "break"

    # ==================== 历史 ====================
    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except:
                self.history = []

    def save_history(self, line):
        self.history.append({
            "t": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "m": line
        })
        if len(self.history) > 500:
            self.history = self.history[-300:]
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False)
        except:
            pass

    # ==================== 连接 ====================
    def do_connect(self):
        if self.running:
            self._disconnect()
            return
        self.nickname = self.name_entry.get().strip()
        if not self.nickname:
            messagebox.showerror("错误", "请输入昵称")
            return

        if self.mode_var.get() == "server":
            pwd = simpledialog.askstring("设置口令",
                                         "设置群口令（至少4位）：",
                                         parent=self.root)
            if not pwd or len(pwd) < 4:
                if pwd:
                    messagebox.showerror("错误", "口令至少4位")
                return
            self.name_entry.config(state="readonly")
            self.connect_btn.config(state="disabled")
            threading.Thread(target=self._start_server,
                             args=(pwd,), daemon=True).start()
        else:
            ip = simpledialog.askstring("加群", "输入服务端的 IP 地址：",
                                       parent=self.root)
            if not ip:
                return
            pwd = simpledialog.askstring("口令", "输入群口令：",
                                        parent=self.root)
            if not pwd:
                return
            self.name_entry.config(state="readonly")
            self.connect_btn.config(state="disabled")
            threading.Thread(target=self._start_client,
                             args=(ip.strip(), pwd), daemon=True).start()

    # ==================== 服务端 ====================
    def _start_server(self, pwd):
        pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()
        local_ip = self.get_local_ip()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", PORT))
            sock.listen(5)
            sock.settimeout(1)

            self.server_sock = sock
            self.running = True
            self.is_server = True

            with self.lock:
                self.clients[sock] = self.nickname

            self.root.after(0, lambda: self.ip_label.config(
                text=f"IP: {local_ip}  口令: {pwd}", fg="green"))
            self.root.after(0, lambda: self.connect_btn.config(
                text="⏹ 关闭", bg="#f44336", state="normal"))
            self.root.after(0, lambda: self.send_btn.config(state="normal"))
            self.root.after(0, lambda: self.set_status(
                f"🟢 群已创建 · 口令: {pwd}"))
            self.root.after(0, lambda: self.log(
                f"🟢 群已创建，IP: {local_ip}  口令: {pwd}"))
            self.root.after(0, self.update_user_list)

            while self.running:
                try:
                    client, addr = sock.accept()
                    threading.Thread(target=self._handle_client,
                                     args=(client, addr, pwd_hash),
                                     daemon=True).start()
                except socket.timeout:
                    continue
                except:
                    break
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror(
                "服务端错误",
                f"启动失败: {e}"))
            self.root.after(0, lambda: self.log(f"❌ 服务端错误: {e}"))
            self._disconnect()

    def _handle_client(self, client, addr, pwd_hash):
        client.settimeout(10)
        try:
            data = client.recv(BUFFER).decode()
            parts = data.split(":", 2)
            if len(parts) < 3 or parts[0] != "AUTH":
                client.close()
                return
            _, client_hash, client_name = parts
            if client_hash != pwd_hash:
                client.sendall(b"AUTH_FAIL")
                client.close()
                return
            client.sendall(b"AUTH_OK")

            with self.lock:
                self.clients[client] = client_name
            self.root.after(0, lambda: self.log(
                f"🔗 {client_name} ({addr[0]}) 加入了群聊"))
            self.root.after(0, self.update_user_list)
            self._broadcast(f"💬 {client_name} 加入了群聊", exclude=client)

            while self.running:
                try:
                    hdr = _recv_exact(client, 4)
                    if hdr is None:
                        break
                    ptype = hdr.decode()
                    if ptype == "MSG:":
                        meta = _recv_exact(client, 8)
                        if meta is None:
                            break
                        body_len = int(meta.decode().strip())
                        body = _recv_exact(client, body_len)
                        if body is None:
                            break
                        content = body.decode()
                        ts = datetime.datetime.now().strftime("%m-%d %H:%M:%S")
                        self.root.after(0, lambda c=content,
                                        n=client_name, t=ts:
                                        self.log(f"[{t}] {n}: {c}"))
                        self._broadcast_raw(
                            f"MSG:{client_name}:{content}", exclude=client)

                    elif ptype == "IMG:":
                        name_len = int(_recv_exact(client, 8).decode().strip())
                        sender_name = _recv_exact(client, name_len).decode()
                        data_len = int(_recv_exact(client, 8).decode().strip())
                        remain = data_len
                        chunks = []
                        while remain > 0:
                            chunk = _recv_exact(client, min(BUFFER, remain))
                            if chunk is None:
                                break
                            chunks.append(chunk)
                            remain -= len(chunk)
                        img_data = b"".join(chunks)
                        self._handle_image_data(sender_name, img_data)
                        # 转发给其他人（包含发送者信息）
                        self._broadcast_raw(
                            b"IMG:" + f"{len(sender_name):<8}".encode()
                            + sender_name.encode()
                            + f"{data_len:<8}".encode()
                            + img_data, exclude=client)
                except:
                    break
        except:
            pass
        finally:
            with self.lock:
                if client in self.clients:
                    name = self.clients.pop(client)
                    self.root.after(0, lambda n=name: self.log(
                        f"🔌 {n} 离开了群聊"))
                    self.root.after(0, self.update_user_list)
                    self._broadcast(f"💬 {name} 离开了群聊")
            try:
                client.close()
            except:
                pass

    # ==================== 客户端 ====================
    def _start_client(self, ip, pwd):
        pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, PORT))
            sock.settimeout(None)

            self.client_sock = sock
            self.running = True

            self.root.after(0, lambda: self.ip_label.config(
                text=f"IP: {ip}", fg="green"))
            self.root.after(0, lambda: self.connect_btn.config(
                text="⏹ 断开", bg="#f44336", state="normal"))
            self.root.after(0, lambda: self.send_btn.config(state="normal"))
            self.root.after(0, lambda: self.set_status(f"🟢 已连接 {ip}"))
            self.root.after(0, lambda: self.log(
                f"🔗 正在连接 {ip}:{PORT} ..."))

            sock.sendall(f"AUTH:{pwd_hash}:{self.nickname}".encode())
            resp = sock.recv(BUFFER).decode()
            if resp == "AUTH_FAIL":
                self.root.after(0, lambda: messagebox.showerror(
                    "错误", "❌ 口令错误"))
                self._disconnect()
                return
            self.root.after(0, lambda: self.log("✅ 口令验证通过"))

            while self.running:
                try:
                    hdr = _recv_exact(sock, 4)
                    if hdr is None:
                        break
                    ptype = hdr.decode()
                    if ptype == "MSG:":
                        meta = _recv_exact(sock, 8)
                        if meta is None:
                            break
                        body_len = int(meta.decode().strip())
                        body = _recv_exact(sock, body_len)
                        if body is None:
                            break
                        content = body.decode()
                        if ":" in content:
                            s, m = content.split(":", 1)
                            self.root.after(
                                0, lambda s=s.strip(), m=m.strip():
                                self.show_msg(s, m))
                        else:
                            self.root.after(
                                0, lambda c=content: self.log(f"💬 {c}"))
                    elif ptype == "IMG:":
                        name_len = int(_recv_exact(sock, 8).decode().strip())
                        sender_name = _recv_exact(sock, name_len).decode()
                        data_len = int(_recv_exact(sock, 8).decode().strip())
                        remain = data_len
                        chunks = []
                        while remain > 0:
                            chunk = _recv_exact(
                                sock, min(BUFFER, remain))
                            if chunk is None:
                                break
                            chunks.append(chunk)
                            remain -= len(chunk)
                        img_data = b"".join(chunks)
                        self._handle_image_data(sender_name, img_data)
                except:
                    break

        except socket.timeout:
            self.root.after(
                0, lambda: messagebox.showerror("错误", "连接超时"))
        except ConnectionRefusedError:
            self.root.after(
                0, lambda: messagebox.showerror("错误", "连接被拒绝"))
        except Exception as e:
            self.root.after(
                0, lambda: self.log(f"❌ 连接失败: {e}"))
        self.root.after(0, lambda: self.log("🔌 已断开"))
        self._disconnect()

    # ==================== 广播 ====================
    def _broadcast(self, msg, exclude=None):
        raw = f"MSG:{self.nickname}:{msg}"
        with self.lock:
            for sock in list(self.clients.keys()):
                if sock == exclude or sock == self.server_sock:
                    continue
                try:
                    body = raw.encode()
                    sock.sendall(b"MSG:" + f"{len(body):<8}".encode() + body)
                except:
                    pass

    def _broadcast_raw(self, raw_binary, exclude=None):
        with self.lock:
            for sock in list(self.clients.keys()):
                if sock == exclude or sock == self.server_sock:
                    continue
                try:
                    if isinstance(raw_binary, str):
                        raw_binary = raw_binary.encode()
                    sock.sendall(raw_binary)
                except:
                    pass

    def update_user_list(self):
        names = [self.nickname]
        with self.lock:
            for _, name in self.clients.items():
                if name not in names:
                    names.append(name)
        self.user_var.set(f"👥 在线: {' · '.join(names)}")
        self.online_label.config(text=f"👥 {len(names)}人")

    # ==================== 发送消息 ====================
    def send_msg(self):
        text = self.msg_entry.get("1.0", tk.END).strip()
        if not text or not self.running:
            return
        self.msg_entry.delete("1.0", tk.END)
        self.show_msg(self.nickname, text)
        self.save_history(f"{self.nickname}: {text}")

        if self.is_server:
            self._broadcast(text)
        else:
            try:
                body = f"{self.nickname}:{text}".encode()
                self.client_sock.sendall(
                    b"MSG:" + f"{len(body):<8}".encode() + body)
            except:
                self.log("❌ 发送失败")
                self._disconnect()

    # ==================== 图片 ====================
    def send_image_dialog(self):
        if not self.running:
            messagebox.showwarning("提示", "请先加入群聊")
            return
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[
                ("图片", "*.png *.jpg *.jpeg *.gif *.bmp"),
                ("所有文件", "*.*")
            ])
        if not path:
            return
        size = os.path.getsize(path)
        if size > MAX_IMG_SIZE:
            messagebox.showerror("错误", f"图片太大（{size//1024}KB），最大支持5MB")
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
            self._show_image(self.nickname, fpath)

            payload = b"IMG:" + f"{len(self.nickname):<8}".encode() \
                      + self.nickname.encode() + f"{len(img_bytes):<8}".encode() + img_bytes
            if self.is_server:
                self._broadcast_raw(payload, exclude=None)
            else:
                self.client_sock.sendall(payload)
        except Exception as e:
            self.log(f"❌ 图片发送失败: {e}")

    def _handle_image_data(self, sender, img_bytes):
        if len(img_bytes) > MAX_IMG_SIZE:
            self.root.after(0, lambda: self.log(
                f"❌ 收到超大图片 ({len(img_bytes)//1024}KB)，已跳过"))
            return
        try:
            self.img_counter += 1
            fname = f"img_{int(time.time())}_{self.img_counter}.png"
            fpath = os.path.join(IMG_DIR, fname)
            with open(fpath, "wb") as f:
                f.write(img_bytes)
            # 在后台线程缩放，避免卡 UI
            threading.Thread(target=self._process_and_show_image,
                             args=(sender, fpath), daemon=True).start()
        except Exception as e:
            self.root.after(0, lambda: self.log(f"❌ 图片接收失败: {e}"))

    def _process_and_show_image(self, sender, fpath):
        """后台缩放图片，再切回主线程显示"""
        try:
            from PIL import Image, ImageTk
            img = Image.open(fpath)
            max_w, max_h = 200, 300
            w, h = img.size
            if w > max_w or h > max_h:
                ratio = min(max_w / w, max_h / h)
                w, h = int(w * ratio), int(h * ratio)
                img = img.resize((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.root.after(0, lambda: self._display_image(sender, fpath, photo))
        except ImportError:
            self.root.after(0, lambda: self.log(
                f"[{datetime.datetime.now().strftime('%m-%d %H:%M:%S')}] {sender}: "
                f"[图片] {os.path.basename(fpath)}"))
            self.root.after(0, lambda: self.log(
                "   (需安装 Pillow: pip install Pillow)"))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"❌ 图片处理失败: {e}"))

    def _display_image(self, sender, fpath, photo):
        """主线程中显示图片"""
        ts = datetime.datetime.now().strftime("%m-%d %H:%M:%S")
        self.log(f"[{ts}] {sender}: [图片] {os.path.basename(fpath)}", save=False)
        self.msg_area.config(state="normal")
        self.msg_area.image_create(tk.END, image=photo)
        self.msg_area.insert(tk.END, "\n")
        self.msg_area.see(tk.END)
        self.msg_area.config(state="disabled")
        self._images.append(photo)
        self._last_img_path = fpath

    # ==================== 表情包 ====================
    def on_msg_right_click(self, event):
        """右键菜单"""
        if self._last_img_path and os.path.exists(self._last_img_path):
            self.msg_menu.tk_popup(event.x_root, event.y_root)

    def save_last_img_as_sticker(self):
        """把最后一张收到的图片存为表情包"""
        if not self._last_img_path or not os.path.exists(self._last_img_path):
            self.log("❌ 没有可保存的图片")
            return
        fname = f"sticker_{int(time.time())}.png"
        dst = os.path.join(STICKER_DIR, fname)
        try:
            from PIL import Image
            img = Image.open(self._last_img_path)
            img.save(dst)
            self.log(f"✅ 已保存表情包: {fname}")
        except Exception as e:
            self.log(f"❌ 保存失败: {e}")

    def open_sticker_picker(self):
        """打开表情包选择窗口"""
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

        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)

        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        row = 0
        col = 0
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
        """发送选中的表情包"""
        if not self.running:
            return
        self._send_image_file(fpath)

    # ==================== 断开 ====================
    def _disconnect(self):
        self.running = False
        self.is_server = False
        with self.lock:
            for sock in list(self.clients.keys()):
                try:
                    sock.close()
                except:
                    pass
            self.clients.clear()
        try:
            if self.server_sock:
                self.server_sock.close()
        except:
            pass
        try:
            if self.client_sock:
                self.client_sock.close()
        except:
            pass
        self.server_sock = None
        self.client_sock = None
        self.root.after(0, lambda: self.connect_btn.config(
            text="🚀 启动", bg="#4CAF50", state="normal"))
        self.root.after(0, lambda: self.send_btn.config(state="disabled"))
        self.root.after(0, lambda: self.ip_label.config(
            text="状态: 就绪", fg="#888"))
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
    app = LanChatPro(root)
    root.mainloop()
