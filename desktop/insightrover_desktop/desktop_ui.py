"""Native connection guide. Network work stays off the Tk event loop."""
import ctypes
import json
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from . import VERSION
from .config import normalize_address
from .vehicle import VehicleSession, Cancelled, friendly_error, validate_login, validate_wifi

BG = '#F3F6FA'
INK = '#172A41'
MUTED = '#52647A'
TEAL = '#087F82'
LINE = '#DCE4ED'


def configure_style(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Microsoft YaHei UI', 10), background=BG, foreground=INK)
    style.configure('Card.TFrame', background='white')
    style.configure('Card.TLabel', background='white', foreground=INK)
    style.configure('Hint.TLabel', background='white', foreground=MUTED, font=('Microsoft YaHei UI', 9))
    style.configure('Title.TLabel', background='white', foreground=INK, font=('Microsoft YaHei UI', 17, 'bold'))
    style.configure('TEntry', padding=8, fieldbackground='white', bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    style.map('TEntry', bordercolor=[('focus', TEAL)])
    style.configure('TButton', padding=(14, 10), background='white', foreground=INK, bordercolor=LINE)
    style.map('TButton', background=[('active', '#E9F1F5')], bordercolor=[('focus', TEAL)])
    style.configure('Primary.TButton', background=TEAL, foreground='white', borderwidth=0, padding=(18, 11))
    style.map('Primary.TButton', background=[('disabled', '#BCD0D2'), ('active', '#06676A')], foreground=[('disabled', '#435D63')])
    style.configure('Card.TRadiobutton', background='white', padding=(0, 7), foreground=INK)
    style.configure('Card.TCheckbutton', background='white', foreground=MUTED)
    style.configure('TProgressbar', background=TEAL, troughcolor='#E8EFF5', borderwidth=0)


def create_admin(root, config):
    if config.has_users():
        return True
    dialog = tk.Toplevel(root)
    dialog.title('首次使用 · 创建网页管理员')
    dialog.geometry('480x440')
    dialog.configure(bg='white')
    dialog.transient(root)
    dialog.grab_set()
    box = ttk.Frame(dialog, style='Card.TFrame', padding=26)
    box.pack(fill='both', expand=True)
    ttk.Label(box, text='创建网页管理员', style='Title.TLabel').pack(anchor='w')
    ttk.Label(box, text='此账户用于登录控制台，与小车 SSH 账户分开。', style='Hint.TLabel').pack(anchor='w', pady=(8, 14))
    user, password, again = tk.StringVar(value='admin'), tk.StringVar(), tk.StringVar()
    for label, var, secret in [('用户名', user, False), ('密码（至少 8 位）', password, True), ('确认密码', again, True)]:
        ttk.Label(box, text=label, style='Card.TLabel').pack(anchor='w', pady=(6, 4))
        ttk.Entry(box, textvariable=var, show='●' if secret else '').pack(fill='x')
    ready = []

    def save():
        if password.get() != again.get():
            messagebox.showerror('请检查密码', '两次输入的密码不一致。', parent=dialog)
            return
        try:
            from .server import initialize
            initialize(config, {'username': user.get().strip(), 'password': password.get()})
        except Exception as exc:
            messagebox.showerror('账户未创建', str(exc), parent=dialog)
            return
        ready.append(True)
        password.set('')
        again.set('')
        dialog.destroy()

    ttk.Button(box, text='创建账户', style='Primary.TButton', command=save).pack(fill='x', pady=(20, 0))
    root.wait_window(dialog)
    return bool(ready)


class DesktopWindow:
    def __init__(self, root, config, backend, preview=False):
        self.root, self.config, self.backend = root, config, backend
        self.preview = preview
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.busy = False
        self.closed = False
        self.worker = None
        self.restarts = 0
        self.session_password = ''
        root.title('InsightRover 智巡 · 连接小车')
        root.geometry('960x760')
        root.minsize(880, 700)
        from .launcher import resources
        icon_file = (Path(sys._MEIPASS)/'desktop-assets/insightrover.ico' if getattr(sys, 'frozen', False)
                     else Path(__file__).resolve().parents[1]/'assets/insightrover.ico')
        if os.name == 'nt' and icon_file.exists():
            root.iconbitmap(default=str(icon_file))
        icon_path = resources()/'brand/logo-transparent.png'
        if os.name != 'nt' and icon_path.exists():
            self.icon = tk.PhotoImage(file=str(icon_path))
            root.iconphoto(True, self.icon)
        configure_style(root)
        self.ip = tk.StringVar(value=config.value['ip'])
        self.port = tk.StringVar(value=str(config.value['port']))
        self.user = tk.StringVar(value=config.value.get('ssh_user', 'jetson'))
        self.ssh_port = tk.StringVar(value=str(config.value.get('ssh_port', 22)))
        self.password = tk.StringVar()
        self.show_password = tk.BooleanVar()
        self.change_wifi = tk.StringVar(value='no')
        self.ssid, self.wifi_password = tk.StringVar(), tk.StringVar()
        self.hidden = tk.BooleanVar()
        self.status_title = tk.StringVar(value='准备连接小车')
        self.status_detail = tk.StringVar(value='填写连接信息后，应用会自动启动小车服务和本机后台。')
        self.build()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)
        root.after(2000, self.monitor)

    def build(self):
        header = tk.Frame(self.root, bg=INK, height=92)
        header.pack(fill='x')
        header.pack_propagate(False)
        mark = tk.Canvas(header, width=44, height=44, bg=INK, highlightthickness=0)
        mark.pack(side='left', padx=(28, 16))
        mark.create_oval(3, 3, 41, 41, outline='#7DE0D4', width=2)
        mark.create_polygon(13, 30, 23, 11, 32, 30, 23, 25, fill='#7DE0D4', outline='')
        wordmark = tk.Frame(header, bg=INK)
        wordmark.pack(side='left')
        tk.Label(wordmark, text='InsightRover  智巡', font=('Microsoft YaHei UI', 19, 'bold'), bg=INK, fg='white').pack(anchor='w')
        tk.Label(wordmark, text='连接设备，开始你的巡检工作', font=('Microsoft YaHei UI', 10), bg=INK, fg='#C3D2E3').pack(anchor='w', pady=(3, 0))
        tk.Label(header, text=f'WINDOWS  /  {VERSION}', font=('Segoe UI', 9), bg=INK, fg='#C3D2E3').pack(side='right', padx=28)
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill='both', expand=True, padx=24, pady=22)
        side = tk.Frame(body, bg=BG, width=175)
        side.pack(side='left', fill='y', padx=(0, 22))
        side.pack_propagate(False)
        self.steps = []
        for number, title, detail in [('01', '连接设置', 'IP、登录与 Wi-Fi'), ('02', '启动服务', '自动检查并启动'), ('03', '登录控制台', '地图与实时状态')]:
            item = tk.Frame(side, bg=BG)
            item.pack(fill='x', pady=(6, 24))
            badge = tk.Label(item, text=number, font=('Segoe UI', 16, 'bold'), fg=TEAL, bg=BG)
            badge.pack(anchor='w')
            tk.Label(item, text=title, font=('Microsoft YaHei UI', 12, 'bold'), bg=BG, fg=INK).pack(anchor='w', pady=(6, 5))
            tk.Label(item, text=detail, font=('Microsoft YaHei UI', 9), bg=BG, fg=MUTED).pack(anchor='w')
            self.steps.append(badge)
        tk.Label(side, text='数据保存在此电脑\n升级后保留地图与账户', justify='left', font=('Microsoft YaHei UI', 9), fg=MUTED, bg=BG).pack(side='bottom', anchor='w', pady=10)
        right = tk.Frame(body, bg=BG)
        right.pack(side='left', fill='both', expand=True)
        shell = tk.Frame(right, bg='white', highlightbackground=LINE, highlightthickness=1)
        shell.pack(fill='both', expand=True)
        canvas = tk.Canvas(shell, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        form = ttk.Frame(canvas, style='Card.TFrame', padding=20)
        window = canvas.create_window((0, 0), window=form, anchor='nw')
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        form.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Enter>', lambda e: canvas.bind_all('<MouseWheel>', lambda event: canvas.yview_scroll(int(-event.delta/120), 'units')))
        canvas.bind('<Leave>', lambda e: canvas.unbind_all('<MouseWheel>'))
        ttk.Label(form, text='连接你的小车', style='Title.TLabel').pack(anchor='w')
        ttk.Label(form, text='电脑与小车需处于可互相访问的局域网。', style='Hint.TLabel').pack(anchor='w', pady=(7, 20))
        ttk.Label(form, text='本次需要更换小车 Wi-Fi 吗？', style='Card.TLabel', font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w')
        choices = ttk.Frame(form, style='Card.TFrame')
        choices.pack(fill='x', pady=(5, 14))
        self.choices = choices
        ttk.Radiobutton(choices, text='不需要，直接启动', value='no', variable=self.change_wifi, style='Card.TRadiobutton', command=self.toggle_wifi).pack(side='left', padx=(0, 20))
        ttk.Radiobutton(choices, text='需要，更换 Wi-Fi', value='yes', variable=self.change_wifi, style='Card.TRadiobutton', command=self.toggle_wifi).pack(side='left')
        self.wifi_box = ttk.Frame(form, style='Card.TFrame')
        self.wifi_box.columnconfigure(0, weight=1)
        self.wifi_box.columnconfigure(1, weight=1)
        self.entry(self.wifi_box, '目标 Wi-Fi 名称', self.ssid, 0, 0)
        self.entry(self.wifi_box, 'Wi-Fi 密码', self.wifi_password, 0, 1, secret=True)
        ttk.Checkbutton(self.wifi_box, text='隐藏网络', variable=self.hidden, style='Card.TCheckbutton').grid(row=2, column=0, sticky='w', pady=8)
        ttk.Label(self.wifi_box, text='切换后请让电脑加入同一网络，并确认小车的新 IP。', style='Hint.TLabel', wraplength=490).grid(row=3, column=0, columnspan=2, sticky='w', pady=(0, 12))
        address = ttk.Frame(form, style='Card.TFrame')
        address.pack(fill='x')
        address.columnconfigure(0, weight=1)
        self.entry(address, '小车当前 IP', self.ip, 0, 0)
        self.entry(address, '网页端口', self.port, 0, 1, width=9)
        ttk.Label(form, text='小车登录', style='Card.TLabel', font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w', pady=(18, 3))
        ttk.Label(form, text='用于启动小车服务；密码仅在本次运行期间使用。', style='Hint.TLabel').pack(anchor='w', pady=(0, 8))
        login = ttk.Frame(form, style='Card.TFrame')
        login.pack(fill='x')
        login.columnconfigure(0, weight=1)
        login.columnconfigure(1, weight=1)
        self.entry(login, 'SSH 用户名', self.user, 0, 0)
        self.password_entry = self.entry(login, 'SSH 登录密码', self.password, 0, 1, secret=True)
        details = ttk.Frame(form, style='Card.TFrame')
        details.pack(fill='x', pady=(6, 12))
        ttk.Checkbutton(details, text='显示登录密码', variable=self.show_password, style='Card.TCheckbutton',
                        command=lambda: self.password_entry.configure(show='' if self.show_password.get() else '●')).pack(side='left')
        ttk.Label(details, text='SSH 端口', style='Hint.TLabel').pack(side='left', padx=(20, 7))
        ttk.Entry(details, textvariable=self.ssh_port, width=6).pack(side='left')
        self.action_box = ttk.Frame(right)
        self.action_box.pack(fill='x', pady=(12, 0))
        self.connect_button = ttk.Button(self.action_box, text='连接并启动小车', style='Primary.TButton', command=self.begin)
        self.connect_button.pack(fill='x')
        ttk.Label(self.action_box, text='服务就绪后自动打开登录页；启动不会发送移动指令。', wraplength=550).pack(anchor='w', pady=(7, 0))
        status = tk.Frame(right, bg='#E8F3F2', padx=18, pady=13)
        status.pack(fill='x', pady=(12, 0))
        self.status_label = tk.Label(status, textvariable=self.status_title, font=('Microsoft YaHei UI', 11, 'bold'), bg='#E8F3F2', fg=TEAL, anchor='w')
        self.status_label.pack(fill='x')
        tk.Label(status, textvariable=self.status_detail, font=('Microsoft YaHei UI', 9), bg='#E8F3F2', fg=INK, justify='left', wraplength=550, anchor='w').pack(fill='x', pady=(5, 0))
        self.progressbar = ttk.Progressbar(status, mode='indeterminate')
        self.progressbar.pack(fill='x', pady=(10, 0))
        footer = ttk.Frame(right)
        footer.pack(fill='x', pady=(10, 0))
        self.offline_button = ttk.Button(footer, text='离线打开控制台', command=self.open_offline)
        self.offline_button.pack(side='left')
        ttk.Button(footer, text='数据目录', command=lambda: os.startfile(self.config.root)).pack(side='right')
        self.cancel_button = ttk.Button(footer, text='取消', command=self.cancelled.set, state='disabled')
        self.cancel_button.pack(side='right', padx=8)

    def entry(self, parent, label, variable, row, column, width=24, secret=False):
        pad = (0, 12) if column == 0 else (0, 0)
        ttk.Label(parent, text=label, style='Card.TLabel').grid(row=row, column=column, sticky='w', pady=(0, 6), padx=pad)
        entry = ttk.Entry(parent, textvariable=variable, width=width, show='●' if secret else '')
        entry.grid(row=row+1, column=column, sticky='ew', padx=pad)
        return entry

    def toggle_wifi(self):
        if self.change_wifi.get() == 'yes':
            self.wifi_box.pack(fill='x', after=self.choices, pady=(0, 12))
            self.connect_button.configure(text='更换 Wi-Fi 并连接')
        else:
            self.wifi_box.pack_forget()
            self.connect_button.configure(text='连接并启动小车')

    def update_status(self, title, detail, error=False):
        self.status_title.set(title)
        self.status_detail.set(detail)
        self.status_label.configure(fg='#A73530' if error else TEAL)

    def request_ui(self, callback):
        event = threading.Event()
        result = []
        self.events.put(('question', (callback, event, result)))
        while not event.wait(.15):
            if self.closed:
                raise Cancelled('应用已关闭')
        if self.cancelled.is_set():
            raise Cancelled('已取消操作；请确认小车当前网络状态后重试。')
        return result[0] if result else None

    def ask_address(self, previous):
        def ask():
            while True:
                answer = simpledialog.askstring('确认换网后的 IP',
                    '换网指令已提交，尚未验证成功。\n\n请先让电脑加入目标 Wi-Fi，再填写小车的新 IP。\n可在路由器设备列表或小车本机查看。\nIP 未变化可保留原值；取消后可稍后重试。',
                    initialvalue=previous, parent=self.root)
                if answer is None:
                    return None
                try:
                    host, _ = normalize_address(answer)
                    if not host:
                        raise ValueError()
                    return host
                except ValueError:
                    messagebox.showerror('地址无效', '请填写有效的 IP 地址。', parent=self.root)
        return self.request_ui(ask)

    def begin(self):
        if self.busy or self.preview:
            return
        try:
            host, port = normalize_address(self.ip.get(), self.port.get())
            if not host:
                raise ValueError('请填写小车当前 IP')
            user, ssh_port = validate_login(self.user.get().strip(), self.ssh_port.get())
            password = self.password.get() or self.session_password
            if not password:
                raise ValueError('请输入小车 SSH 登录密码')
            wifi = None
            if self.change_wifi.get() == 'yes':
                validate_wifi(self.ssid.get(), self.wifi_password.get())
                wifi = dict(ssid=self.ssid.get(), password=self.wifi_password.get(), interface='', hidden=self.hidden.get())
        except ValueError as exc:
            self.update_status('请检查连接信息', str(exc), error=True)
            return
        self.busy = True
        self.cancelled.clear()
        self.connect_button.configure(state='disabled')
        self.offline_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.progressbar.start(12)
        self.steps[1].configure(fg=TEAL)
        self.update_status('正在连接', '请保持电脑与小车网络可达…')
        self.session_password = password
        self.password.set('')
        self.wifi_password.set('')

        def work():
            try:
                session = VehicleSession(self.config, user, password, ssh_port,
                    lambda title, detail: self.request_ui(lambda: messagebox.askyesno(title, detail, parent=self.root)),
                    lambda title, detail: self.events.put(('progress', (title, detail))), self.cancelled)
                target = host
                if wifi:
                    target = session.switch_wifi(host, port, wifi, self.ask_address)
                    # Preserve the verified new address even if subsequent service startup fails.
                    self.events.put(('address', (target, port)))
                state = session.start(target, port)
                session.check_cancelled()
                self.events.put(('ready', (target, port, user, ssh_port, state)))
            except Exception as exc:
                detail = friendly_error(exc)
                for secret in (password, wifi.get('password') if wifi else None):
                    if secret:
                        detail = detail.replace(secret, '[密码已隐藏]')
                self.events.put(('failed', ('操作已取消' if isinstance(exc, Cancelled) else '连接未完成', detail)))
            finally:
                if wifi:
                    wifi['password'] = ''
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def finish(self):
        self.busy = False
        self.progressbar.stop()
        self.connect_button.configure(state='normal')
        self.offline_button.configure(state='normal')
        self.cancel_button.configure(state='disabled')

    def start_backend(self, host=None, port=None):
        if not create_admin(self.root, self.config):
            return False
        if host is not None:
            if self.config.value['ip'] != host or self.config.value['port'] != port:
                self.backend.stop()
            self.config.set_address(host, port)
        if self.backend.process is None:
            self.backend.start()
        webbrowser.open(self.backend.url+'/#/slam')
        self.offline_button.configure(text='打开控制台')
        return True

    def open_offline(self):
        if self.busy or self.preview:
            return
        try:
            self.update_status('正在准备控制台', '正在启动本机后台…')
            self.root.update_idletasks()
            if self.start_backend():
                self.update_status('控制台已打开', '可登录并管理本机数据；实时功能需要连接小车。')
        except Exception as exc:
            self.update_status('后台未就绪', str(exc), error=True)

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'question':
                callback, event, result = data
                try:
                    if not self.cancelled.is_set():
                        result.append(callback())
                finally:
                    event.set()
            elif kind == 'progress':
                self.update_status(*data)
            elif kind == 'address':
                self.ip.set(data[0])
                self.config.set_address(*data)
                # Stop a local proxy with an old address before switching its configuration.
                self.backend.stop()
            elif kind == 'failed':
                self.finish()
                self.update_status(*data, error=True)
            elif kind == 'ready':
                self.finish()
                if self.cancelled.is_set():
                    self.update_status('已取消打开控制台', '小车服务可能已启动；可确认状态后重新连接。')
                    continue
                host, port, user, ssh_port, state = data
                try:
                    self.ip.set(host)
                    self.config.value.update(ssh_user=user, ssh_port=ssh_port)
                    self.config.save()
                    self.update_status('小车已就绪', '正在准备本机后台与登录页…')
                    self.root.update_idletasks()
                    if self.start_backend(host, port):
                        self.steps[2].configure(fg=TEAL)
                        self.change_wifi.set('no')
                        self.toggle_wifi()
                        mode = '停车' if state['mode'] == 'stop' else state['mode']
                        self.update_status('已连接 · 控制台已打开', f'小车 {host} · 当前模式：{mode}。请在浏览器登录网页账户。')
                except Exception as exc:
                    self.update_status('控制台未打开', str(exc), error=True)
        self.root.after(100, self.poll)

    def monitor(self):
        if self.closed:
            return
        if not self.busy and self.backend.process is not None and self.backend.process.poll() is not None:
            self.update_status('正在恢复本机后台', '后台意外退出，正在重新启动…')
            if self.restarts < 3:
                self.restarts += 1
                try:
                    self.backend.stop()
                    self.backend.start()
                    self.update_status('后台已恢复', '请刷新已打开的控制台。')
                except Exception:
                    self.update_status('后台恢复失败', '请重新打开应用；详细原因见数据目录日志。', error=True)
            else:
                self.update_status('后台多次退出', '请重新打开应用并检查数据目录日志。', error=True)
        self.root.after(2000, self.monitor)

    def close(self):
        if self.busy and not messagebox.askyesno('退出应用', '操作尚未完成。若换网任务已提交，它会继续执行或回退。\n\n确定退出？', parent=self.root):
            return
        self.closed = True
        self.cancelled.set()
        self.session_password = ''
        self.password.set('')
        self.wifi_password.set('')
        self.backend.stop()
        self.root.destroy()


def gui(config, backend_factory, preview=False):
    mutex = None
    if os.name == 'nt' and not preview:
        ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\InsightRoverDesktop')
        if ctypes.windll.kernel32.GetLastError() == 183:
            runtime = config.root/'runtime.json'
            if runtime.exists():
                webbrowser.open(json.loads(runtime.read_text())['url'])
            return
    root = tk.Tk()
    window = DesktopWindow(root, config, backend_factory(config), preview)
    root.mainloop()
    if mutex:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))
