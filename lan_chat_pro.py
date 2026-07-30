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

# 获取正确的路径（兼容 PyInstaller）
def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

HISTORY_FILE = os.path.join(get_base_dir(), "lan_chat_history.json")
IMG_DIR = os.path.join(get_base_dir(), "chat_images")

QUICK_EMOJIS = ["😂","😅","😏","😎","😭","😡","🥴","🤔","👍","👎","❤️","🔥","💀","🎉","🚀","💪","🫡","🤣","😤","😈","🦞","🐶","🌚","💩"]


class LanChatPro:
    def __init__(self, root):
        self.root = root
        self.root.title("LAN Chat Pro")
        self.root.geometry("680x600")
        self.root.minsize(620, 520)

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

        os.makedirs(IMG_DIR, exist_ok=True)
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

        # ===== 聊天区 =====
        self.msg_area = scrolledtext.ScrolledText(
            root, state="disabled", height=18,
            font=("Microsoft YaHei", 10), wrap=tk.WORD)
        self.msg_area.pack(fill="both", padx=8, pady=(2, 4), expand=True)
        self.msg_area.bind("<Control-v>", self.on_paste_img)

        # ===== 在线用户 =====
        self.user_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.user_var, fg="#888",
                 anchor="w", font=("", 9)).pack(fill="x", padx=8)

        # ===== 快捷表情 =====
        emo_frame = tk.Frame(root)
        emo_frame.pack(fill="x", padx=8, pady=(0, 2))
        for e in QUICK_EMOJIS:
            btn = tk.Button(emo_frame, text=e, font=("", 13),
                            width=2, bd=0,
                            command=lambda em=e: self.insert_emoji(em))
            btn.pack(side="left", padx=1)
        tk.Button(emo_frame, text="🖼️", font=("", 13),
                  width=2, bd=0,
                  command=self.send_image_dialog).pack(side="left", padx=2)

        # ===== 输入框 =====
        bottom = tk.Frame(root)
        bottom.pack(fill="x", padx=8, pady=(0, 6))

        self.msg_entry = tk.Text(bottom, height=2,
                                 font=("Microsoft YaHei", 10))
        self.msg_entry.pack(side="left", fill="x", expand=True)
        self.msg_entry.bind("<Return>", self.on_enter)
        self.msg_entry.bind("<Shift-Return>", lambda e: None)

        self.send_btn = tk.Button(bottom, text="发送", width=7,
                                  command=self.send_msg,
                                  state="disabled",
                                  font=("", 9, "bold"),
                                  bg="#2196F3", fg="white")
        self.send_btn.pack(side="right", padx=(4, 0))

        # ===== 状态栏 =====
        self.status_bar = tk.Label(root, text="💡 建群 = 创建房间 | 加群 = 输入对方IP",
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
        ts = datetime.datetime.now().strftime("%m-%d %H:%M")
        self.log(f"[{ts}] {sender}: {content}")

    def set_status(self, text, color="#666"):
        self.status_bar.config(text=text, fg=color)

    def insert_emoji(self, em):
        self.msg_entry.insert(tk.END, em)
        self.msg_entry.focus()

    def on_enter(self, event):
        self.send_msg()
        return "break"

    def on_mode_change(self):
        if self.running:
            self.disconnect()

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
            "t": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
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
                f"🟢 群已创建 · 口令: {pwd} · 等待好友加入"))
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
                f"启动失败: {e}\n\n可能端口 {PORT} 已被占用，检查防火墙设置。"))
            self.root.after(0, lambda: self.log(f"❌ 服务端错误: {e}"))
            self._disconnect()

    def _handle_client(self, client, addr, pwd_hash):
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
                    data = client.recv(BUFFER).decode()
                    if not data:
                        break
                    if data.startswith("MSG:"):
                        content = data[4:]
                        self.root.after(0, lambda c=content,
                                        n=client_name: self.show_msg(n, c))
                        self._broadcast(
                            f"{client_name}: {content}", exclude=client)
                    elif data.startswith("IMG:"):
                        parts = data.split(":", 3)
                        if len(parts) == 4:
                            _, ext, _, img_data = parts
                            self._handle_image(client_name, ext, img_data)
                            self._broadcast_raw(data, exclude=client)
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
                    data = sock.recv(BUFFER).decode()
                    if not data:
                        break
                    if data.startswith("MSG:"):
                        content = data[4:]
                        if ":" in content:
                            s, m = content.split(":", 1)
                            self.root.after(
                                0, lambda s=s.strip(), m=m.strip():
                                self.show_msg(s, m))
                        else:
                            self.root.after(
                                0, lambda c=content: self.log(f"💬 {c}"))
                    elif data.startswith("IMG:"):
                        parts = data.split(":", 3)
                        if len(parts) == 4:
                            _, ext, _, img_data = parts
                            self._handle_image("未知", ext, img_data)
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
        with self.lock:
            for sock, name in list(self.clients.items()):
                if sock == exclude or sock == self.server_sock:
                    continue
                try:
                    sock.sendall(f"MSG:{msg}".encode())
                except:
                    pass

    def _broadcast_raw(self, raw, exclude=None):
        with self.lock:
            for sock in list(self.clients.keys()):
                if sock == exclude or sock == self.server_sock:
                    continue
                try:
                    sock.sendall(raw.encode())
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

    # ==================== 发送 ====================
    def send_msg(self):
        text = self.msg_entry.get("1.0", tk.END).strip()
        if not text or not self.running:
            return
        self.msg_entry.delete("1.0", tk.END)
        self.show_msg(self.nickname, text)
        self.save_history(f"{self.nickname}: {text}")

        if self.is_server:
            self._broadcast(f"{self.nickname}: {text}")
        else:
            try:
                self.client_sock.sendall(
                    f"MSG:{self.nickname}: {text}".encode())
            except:
                self.log("❌ 发送失败")
                self._disconnect()

    # ==================== 图片 ====================
    def send_image_dialog(self):
        if not self.running:
            return
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.bmp")])
        if path:
            self._send_image_file(path)

    def on_paste_img(self, event):
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img:
                path = os.path.join(
                    IMG_DIR,
                    f"paste_{int(time.time())}.png")
                img.save(path)
                self._send_image_file(path)
                return "break"
        except:
            pass

    def _send_image_file(self, path):
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            ext = os.path.splitext(path)[1].lower().replace(".", "")
            payload = f"IMG:{ext}:{len(data)}:{data}"

            if self.is_server:
                self._show_image(self.nickname, path)
                self._broadcast_raw(payload)
            else:
                self.client_sock.sendall(payload.encode())
                self._show_image(self.nickname, path)
        except Exception as e:
            self.log(f"❌ 图片发送失败: {e}")

    def _handle_image(self, sender, ext, data_b64):
        try:
            img_data = base64.b64decode(data_b64)
            self.img_counter += 1
            fname = f"img_{int(time.time())}_{self.img_counter}.{ext}"
            fpath = os.path.join(IMG_DIR, fname)
            with open(fpath, "wb") as f:
                f.write(img_data)
            self.root.after(0, lambda: self._show_image(sender, fpath))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"❌ 图片接收失败: {e}"))

    def _show_image(self, sender, fpath):
        ts = datetime.datetime.now().strftime("%m-%d %H:%M")
        self.log(f"[{ts}] {sender}: [图片] {os.path.basename(fpath)}")
        try:
            from PIL import Image, ImageTk
            img = Image.open(fpath)
            max_w = 200
            w, h = img.size
            if w > max_w:
                h = int(h * max_w / w)
                w = max_w
            img = img.resize((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.msg_area.config(state="normal")
            self.msg_area.image_create(tk.END, image=photo)
            self.msg_area.insert(tk.END, "\n")
            self.msg_area.see(tk.END)
            self.msg_area.config(state="disabled")
            self._images.append(photo)
        except ImportError:
            self.log("   (需要 Pillow 显示图片: pip install Pillow)")

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
