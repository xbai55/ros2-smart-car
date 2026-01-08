import sys
import socket
from PyQt6.QtWidgets import (QApplication, QWidget, QGridLayout, 
                             QPushButton, QVBoxLayout, QLabel)
from PyQt6.QtCore import Qt, QSize

# --- 配置区 ---
JETSON_IP = '192.168.1.11' 
PORT = 9999

class RobotControlPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.init_socket()
        self.init_ui()
        # 强行给全窗口安装事件过滤器，拦截系统对空格的默认处理
        self.installEventFilter(self)

    def init_socket(self):
        try:
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.connect((JETSON_IP, PORT))
            self.status_msg = f"✅ 已连接: {JETSON_IP}"
        except:
            self.status_msg = "❌ 未连接"

    def init_ui(self):
        self.setWindowTitle('麦轮小车逻辑修正版')
        self.setFixedSize(480, 420)
        self.setStyleSheet("""
            QWidget { background-color: #1e1e2e; }
            QPushButton { 
                background-color: #44475a; color: white; 
                border-radius: 12px; font-weight: bold; font-size: 15px;
            }
            QPushButton:pressed { background-color: #50fa7b; color: #282a36; }
            QPushButton#stop_btn { background-color: #ff5555; }
        """)

        layout = QVBoxLayout()
        self.status_label = QLabel(self.status_msg)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        grid = QGridLayout()
        self.controls = {
            Qt.Key.Key_W: {'cmd': 'forward', 'name': '前进 (W)'},
            Qt.Key.Key_S: {'cmd': 'backward', 'name': '后退 (S)'},
            Qt.Key.Key_A: {'cmd': 'left', 'name': '左平移 (A)'},
            Qt.Key.Key_D: {'cmd': 'right', 'name': '右平移 (D)'},
            Qt.Key.Key_Q: {'cmd': 'turn_l', 'name': '左旋 (Q)'},
            Qt.Key.Key_E: {'cmd': 'turn_r', 'name': '右旋 (E)'},
            Qt.Key.Key_Space: {'cmd': 'stop', 'name': '刹车 (空格)'}
        }

        self.btn_widgets = {}
        for key, info in self.controls.items():
            btn = QPushButton(info['name'])
            btn.setFixedSize(120, 90)
            # 1. 禁用焦点，防止按钮抢占空格键
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if info['cmd'] == 'stop': btn.setObjectName("stop_btn")
            
            # 点击逻辑
            btn.clicked.connect(lambda checked, c=info['cmd']: self.send_cmd(c))
            self.btn_widgets[key] = btn

        grid.addWidget(self.btn_widgets[Qt.Key.Key_W], 0, 1)
        grid.addWidget(self.btn_widgets[Qt.Key.Key_Q], 1, 0)
        grid.addWidget(self.btn_widgets[Qt.Key.Key_Space], 1, 1)
        grid.addWidget(self.btn_widgets[Qt.Key.Key_E], 1, 2)
        grid.addWidget(self.btn_widgets[Qt.Key.Key_A], 2, 0)
        grid.addWidget(self.btn_widgets[Qt.Key.Key_S], 2, 1)
        grid.addWidget(self.btn_widgets[Qt.Key.Key_D], 2, 2)
        layout.addLayout(grid)
        self.setLayout(layout)

    def send_cmd(self, msg):
        try:
            self.client.send(msg.encode('utf-8'))
            print(f"发送控制信号: {msg}")
        except:
            pass

    # 2. 核心修正逻辑：拦截所有子组件的空格事件
    def eventFilter(self, obj, event):
        if event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Space:
                # 发现空格键，强行中断默认分发过程，直接调用我们的处理函数
                self.process_key_logic(Qt.Key.Key_Space)
                return True # 表示事件已处理，不再向下传递（防止被识别为按钮点击）
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        self.process_key_logic(event.key())

    def process_key_logic(self, key):
        if key in self.controls:
            cmd = self.controls[key]['cmd']
            self.send_cmd(cmd)
            # 视觉上让对应的按钮闪烁一下表示识别成功
            if key in self.btn_widgets:
                self.btn_widgets[key].setDown(True)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        if event.key() in self.btn_widgets:
            self.btn_widgets[event.key()].setDown(False)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    panel = RobotControlPanel()
    panel.show()
    sys.exit(app.exec())