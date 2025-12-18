import os
import sys
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = ''
os.environ['QT_LOGGING_RULES'] = '*.debug=false;qt.qpa.*=false'
import cv2
if 'QT_QPA_PLATFORM_PLUGIN_PATH' in os.environ:
    del os.environ['QT_QPA_PLATFORM_PLUGIN_PATH']
from PyQt5.QtCore import *
from PyQt5 import QtCore
from PyQt5.QtGui import *
from PyQt5.QtWidgets import QMainWindow, QApplication, QPushButton, QVBoxLayout, QWidget, QLabel, QHBoxLayout
import zmq
import base64
import numpy as np
from modbus_client import ModbusClientThread

class Video(QThread):
    frameReady = pyqtSignal(object)  # emits numpy.ndarray (BGR)
    def __init__(self, endpoint: str = "tcp://127.0.0.1:5555", parent=None):
        super().__init__(parent)
        self.endpoint = endpoint
        self._running = False

    def run(self):
        self._running = True
        try:
            context = zmq.Context()
            sock = context.socket(zmq.PAIR)
            # 接收端通常 connect 到发送端的 bind
            try:
                sock.connect(self.endpoint)
            except Exception:
                try:
                    sock.bind(self.endpoint)
                except Exception as e:
                    print(f"ZMQ socket setup error: {e}")
                    return

            poller = zmq.Poller()
            poller.register(sock, zmq.POLLIN)

            while self._running:
                socks = dict(poller.poll(500))
                if sock in socks and socks[sock] & zmq.POLLIN:
                    try:
                        frame_txt = sock.recv_string(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        continue
                    try:
                        img = base64.b64decode(frame_txt)
                        npimg = np.frombuffer(img, dtype=np.uint8)
                        source = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
                        if source is not None:
                            self.frameReady.emit(source)
                    except Exception as e:
                        print(f"frame decode error: {e}")
                        continue
        finally:
            try:
                poller.unregister(sock)
            except Exception:
                pass
            try:
                sock.close(0)
            except Exception:
                pass

    def stop(self):
        self._running = False
        self.wait(1000)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        #加载页面
        self.setWindowTitle("监控与控制界面")
        self.resize(800, 600)
        #主部件和主布局
        central_widget = QWidget()
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        #视频窗口
        self.video_label = QLabel("视频窗口")
        self.video_label.setStyleSheet("background-color: black; color: white; font-size: 24px;")
        self.video_label.setAlignment(QtCore.Qt.AlignCenter)
        self.video_label.setMinimumSize(400, 400)
        main_layout.addWidget(self.video_label, 2)
        #指示灯和按钮
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_widget.setLayout(right_layout)
        main_layout.addWidget(right_widget, 1)
        #运行灯和警报灯
        top_lights_layout = QHBoxLayout()
        self.run_light = QLabel("运行")
        self.run_light.setFixedSize(56, 56)  
        self.run_light.setAlignment(QtCore.Qt.AlignCenter)
        self.run_light.setStyleSheet(
            "background-color: gray; color: white; border-radius: 28px; font-weight: bold; font-size: 14px;"
        )
        self.run_light.setToolTip("运行指示灯")
        top_lights_layout.addWidget(self.run_light)
        top_lights_layout.addSpacing(12)
        self.alarm_light = QLabel("警报")
        self.alarm_light.setFixedSize(56, 56)
        self.alarm_light.setAlignment(QtCore.Qt.AlignCenter)
        self.alarm_light.setStyleSheet(
            "background-color: gray; color: white; border-radius: 28px; font-weight: bold; font-size: 14px;"
        )
        self.alarm_light.setToolTip("警报指示灯")
        top_lights_layout.addWidget(self.alarm_light)
        right_layout.addLayout(top_lights_layout)

        #温度、湿度、次数、时间显示窗口
        self.temp_label = QLabel("温度: --")
        self.temp_label.setStyleSheet("font-size: 16px; background-color: #eee;")
        self.temp_label.setAlignment(QtCore.Qt.AlignCenter)
        self.temp_label.setFixedHeight(40)
        right_layout.addWidget(self.temp_label)
        self.humi_label = QLabel("湿度: --")
        self.humi_label.setStyleSheet("font-size: 16px; background-color: #eee;")
        self.humi_label.setAlignment(QtCore.Qt.AlignCenter)
        self.humi_label.setFixedHeight(40)
        right_layout.addWidget(self.humi_label)
        self.count_label = QLabel("点亮次数：--")
        self.count_label.setStyleSheet("font-size: 16px; background-color: #eee;")
        self.count_label.setAlignment(QtCore.Qt.AlignCenter)
        self.count_label.setFixedHeight(40)
        right_layout.addWidget(self.count_label)
        self.time_label = QLabel("时间: --")
        self.time_label.setStyleSheet("font-size: 16px; background-color: #eee;")
        self.time_label.setAlignment(QtCore.Qt.AlignCenter)
        self.time_label.setFixedHeight(40)
        right_layout.addWidget(self.time_label)
        #停止、运行、解除按钮
        bottom_btn_layout = QHBoxLayout()
        self.btn1 = QPushButton("停止")
        bottom_btn_layout.addWidget(self.btn1)
        self.btn2 = QPushButton("运行")
        bottom_btn_layout.addWidget(self.btn2)
        self.btn3 = QPushButton("解除")
        bottom_btn_layout.addWidget(self.btn3)
        right_layout.addLayout(bottom_btn_layout)
        # 开灯/灭灯按钮
        light_btn_layout = QHBoxLayout()
        self.light_on_btn = QPushButton("开灯")
        self.light_off_btn = QPushButton("灭灯")
        light_btn_layout.addWidget(self.light_on_btn)
        light_btn_layout.addWidget(self.light_off_btn)
        right_layout.addLayout(light_btn_layout)
        right_layout.addStretch()
        #时间显示
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)
        #按钮点击事件连接
        self.btn1.clicked.connect(lambda: self.on_button_click(0))
        self.btn2.clicked.connect(lambda: self.on_button_click(1))
        self.btn3.clicked.connect(lambda: self.on_button_click(2))
        self.light_on_btn.clicked.connect(lambda: self.on_button_click(3))
        self.light_off_btn.clicked.connect(lambda: self.on_button_click(4))

        #启动视频接收线程
        endpoint = os.environ.get('ZMQ_ENDPOINT', 'tcp://127.0.0.1:5555')
        self.video_thread = Video(endpoint)
        self.video_thread.frameReady.connect(self.on_frame)
        self.video_thread.start()
        #启动Modbus通信线程
        modbus_host = os.environ.get('MODBUS_HOST')  #从shell环境变量中获取端口配置
        modbus_serial = os.environ.get('MODBUS_SERIAL')  
        self.modbus_thread = ModbusClientThread(
            host=modbus_host,
            serial_port=modbus_serial,
            slave_id=1,
            poll_interval=0.5
        )
        self.modbus_thread.statusUpdated.connect(self.on_modbus_status)
        self.modbus_thread.connectionStatus.connect(self.on_modbus_connection)
        self.modbus_thread.error.connect(self.on_modbus_error)
        self.modbus_thread.start()

    def update_time(self):
        current_time = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.time_label.setText(f"时间: {current_time}")

    def set_run_light(self, status: bool):
        color = "green" if status else "gray"
        self.run_light.setStyleSheet(
            f"background-color: {color}; color: white; border-radius: 28px; font-weight: bold; font-size: 14px;"
        )

    def set_alarm_light(self, status: bool):
        color = "red" if status else "gray"
        self.alarm_light.setStyleSheet(
            f"background-color: {color}; color: white; border-radius: 28px; font-weight: bold; font-size: 14px;"
        )

    def set_temperature(self, value):
        """温度显示"""
        self.temp_label.setText(f"温度: {value}°C")

    def set_humidity(self, value):
        """湿度显示"""
        self.humi_label.setText(f"湿度: {value}%")

    def on_button_click(self, idx):
        """
        按钮点击处理，idx=0和2,系统状态停止，idx=1,系统运行，3/4=开/关灯
        """
        if not hasattr(self, 'modbus_thread') or not self.modbus_thread._connected:
            print("Modbus未连接")
            return
        
        if idx == 0:  #停止
            self.modbus_thread.set_system_status(0)  # 系统状态=停止
        elif idx == 1:  #运行
            self.modbus_thread.set_system_status(1)  # 系统状态=运行
            self.set_run_light(True)#亮运行灯，关警报灯
            self.set_alarm_light(False)
        elif idx == 2:  #解除警报
            self.modbus_thread.set_system_status(0)  # 系统状态=停止
            self.modbus_thread.control_buzzer(False)  # 关蜂鸣器
            self.modbus_thread.control_red_light(False)  #关闭红灯
            self.set_alarm_light(False)#警报灯关闭
        elif idx == 3:  #开灯
            self.modbus_thread.control_indicator(True)  #点亮LED
        elif idx == 4:  #灭灯
            self.modbus_thread.control_indicator(False)  #关闭LED

    def on_frame(self, frame: np.ndarray):
        """将接收到的视频帧显示到GUI上,设置异常捕获避免程序崩溃"""
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
            pix = QPixmap.fromImage(qimg)
            pix = pix.scaled(self.video_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.video_label.setPixmap(pix)
        except Exception as e:
            print(f"on_frame error: {e}")

    @pyqtSlot(bool, bool, float, float, int, int, int, bool)
    def on_modbus_status(self, fire_detected, sensor_ready, temperature, humidity, 
                        confidence, indicator_count, system_status, alarm_enabled):
        # 根据系统状态设置运行灯和报警灯
        self.set_run_light(system_status == 1)  #运行状态时绿灯
        self.set_alarm_light(system_status == 2 or fire_detected)  #报警状态或火灾时红灯
        self.count_label.setText(f"点亮次数：{indicator_count}")
        self.set_temperature(temperature)
        self.set_humidity(humidity)
        if fire_detected:
            self.setWindowTitle("监控与控制界面 - 火灾警报！")
        else:
            status_text = ["停止", "运行", "报警"][system_status] if system_status <= 2 else "未知"
            self.setWindowTitle(f"监控与控制界面 - 状态: {status_text}")

    @pyqtSlot(bool)
    def on_modbus_connection(self, connected):
        """Modbus 连接状态"""
        status = "已连接" if connected else "未连接"
        self.setWindowTitle(f"监控与控制界面 - Modbus: {status}")

    @pyqtSlot(str)
    def on_modbus_error(self, msg):
        print(f"Modbus错误: {msg}")

    def closeEvent(self, event):
        """关闭窗口时停止线程并清理"""
        try:
            if hasattr(self, 'video_thread') and self.video_thread.isRunning():
                self.video_thread.stop()
        except Exception:
            pass
        try:
            if hasattr(self, 'modbus_thread') and self.modbus_thread.isRunning():
                self.modbus_thread.stop()
        except Exception:
            pass
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow() #实例化MAINwindow
    window.show()#显示GUI
    sys.exit(app.exec_())
