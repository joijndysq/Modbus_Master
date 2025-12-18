import time
import threading
from PyQt5.QtCore import QThread, pyqtSignal
import serial
from modbus import modbus_tcp, modbus_rtu, defines as cst

class ModbusClientThread(QThread):
    """Modbus 异步通信线程"""
    # 参数：(火灾检测, 传感器就绪, 温度, 湿度, 置信度, 指示灯次数, 系统状态, 报警使能)
    statusUpdated = pyqtSignal(bool, bool, float, float, int, int, int, bool)
    # 信号线圈状态（红/绿/蓝/蜂鸣/指示灯）
    coilsUpdated = pyqtSignal(bool, bool, bool, bool, bool)
    connectionStatus = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, host=None, port=502, serial_port='/dev/ttyUSB0', 
                 baudrate=115200, slave_id=1, poll_interval=0.5, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.slave_id = slave_id
        self.poll_interval = poll_interval
        self.client = None
        self._running = False
        self._connected = False
        self._lock = threading.Lock()

    def connect_client(self):
        """建立 Modbus 连接"""
        try:
            if self.serial_port:
                #modbus_rtu.RtuMaster
                ser = serial.Serial(
                    port=self.serial_port,
                    baudrate=self.baudrate,
                    bytesize=8,
                    parity='N',
                    stopbits=1,
                    timeout=1.0
                )
                self.client = modbus_rtu.RtuMaster(ser)
                self.client.set_timeout(1.0)
            elif self.host:
                # 使用本地 modbus_tcp.TcpMaster
                self.client = modbus_tcp.TcpMaster(
                    host=self.host,
                    port=self.port,
                    timeout_in_sec=1.0
                )
            else:
                self.error.emit("未指定Modbus连接参数")
                return False
            #测试连接
            try:
                self.client.execute(self.slave_id, cst.READ_HOLDING_REGISTERS, 0, 1)
                self._connected = True
                self.connectionStatus.emit(True)
                print(f"Modbus连接成功: {self.host or self.serial_port}")
                return True
            except Exception as e:
                self._connected = False
                self.connectionStatus.emit(False)
                self.error.emit(f"连接测试失败: {e}")
                return False
        except Exception as e:
            self.error.emit(f"连接创建失败: {e}")
            return False

    def run(self):
        """线程主循环"""
        self._running = True
        if not self.connect_client():
            return
        
        while self._running:
            try:
                if self._connected:
                    self.read_all_status()
                time.sleep(self.poll_interval)
            except Exception as e:
                self.error.emit(f"轮询错误: {e}")
                time.sleep(1)

    def stop(self):
        """停止线程"""
        self._running = False
        if self.client:
            try:
                self.client.close()
            except:
                pass
        self.wait()

    def write_coil(self, address, value):
        """写入单个线圈 (0=红灯, 1=绿灯, 2=蓝灯, 3=蜂鸣器, 4=指示灯)"""
        with self._lock:
            if not self._connected:
                return False
            try:
                result = self.client.execute(self.slave_id, cst.WRITE_SINGLE_COIL, 
                                  address, output_value=1 if value else 0)
                return result is not None
            except Exception as e:
                self.error.emit(f"写入线圈 {address} 失败: {e}")
                return False
    
    def write_coils(self, values):
        """写入多个线圈"""
        with self._lock:
            if not self._connected:
                return False
            try:
                int_values = [1 if v else 0 for v in values]
                self.client.execute(self.slave_id, cst.WRITE_MULTIPLE_COILS,
                                  0, output_value=int_values)
                return True
            except Exception as e:
                self.error.emit(f"写入多个线圈失败: {e}")
                return False
    
    def read_coils(self):
        """读取所有线圈状态"""
        with self._lock:
            if not self._connected:
                return None
            try:
                data = self.client.execute(self.slave_id, cst.READ_COILS, 0, 5)
                return [bool(v) for v in data]
            except Exception as e:
                return None

    def write_holding_register(self, address, value):
        """写入保持寄存器 (0=系统状态, 1=报警使能, 2=传感器间隔)"""
        with self._lock:
            if not self._connected:
                return False
            try:
                self.client.execute(self.slave_id, cst.WRITE_SINGLE_REGISTER,
                                  address, output_value=value)
                return True
            except Exception as e:
                self.error.emit(f"写入寄存器失败: {e}")
                return False
    
    def read_holding_registers(self):
        """读取保持寄存器"""
        with self._lock:
            if not self._connected:
                return None
            try:
                data = self.client.execute(self.slave_id, cst.READ_HOLDING_REGISTERS, 0, 3)
                return list(data)
            except Exception as e:
                return None

    def read_discrete_inputs(self):
        """读取离散输入（火灾检测、传感器就绪）"""
        with self._lock:
            if not self._connected:
                return None
            try:
                data = self.client.execute(self.slave_id, cst.READ_DISCRETE_INPUTS, 0, 2)
                return [bool(v) for v in data]
            except Exception as e:
                return None

    def read_input_registers(self):
        """读取输入寄存器（温湿度、置信度、次数）"""
        with self._lock:
            if not self._connected:
                return None
            try:
                data = self.client.execute(self.slave_id, cst.READ_INPUT_REGISTERS, 0, 6)
                return list(data)
            except Exception as e:
                return None

    def read_all_status(self):
        """读取所有状态并发出信号"""
        try:
            # 读取离散输入
            discrete = self.read_discrete_inputs()
            if discrete is None:
                self.error.emit("读取离散输入失败")
                return
            fire_detected = discrete[0]
            sensor_ready = discrete[1]
            
            # 读取输入寄存器
            input_regs = self.read_input_registers()
            if input_regs is None:
                self.error.emit("读取输入寄存器失败")
                return
            temp_int = input_regs[0]
            temp_dec = input_regs[1]
            hum_int = input_regs[2]
            hum_dec = input_regs[3]
            confidence = input_regs[4]
            indicator_count = input_regs[5]
            
            temperature = temp_int + temp_dec / 100.0
            humidity = hum_int + hum_dec / 100.0
            
            # 读取保持寄存器
            holding_regs = self.read_holding_registers()
            if holding_regs is None:
                self.error.emit("读取保持寄存器失败")
                return
            system_status = holding_regs[0]
            alarm_enabled = bool(holding_regs[1])
            
            # 读取线圈状态
            coils = self.read_coils()
            if coils is not None:
                self.coilsUpdated.emit(*coils)
            
            # 发送综合状态信号
            self.statusUpdated.emit(
                fire_detected, sensor_ready,
                temperature, humidity,
                confidence, indicator_count,
                system_status, alarm_enabled
            )
        except Exception as e:
            self.error.emit(f"读取状态异常: {e}")

    #便捷控制方法
    def set_system_status(self, status):
        """设置系统状态 (0=停止, 1=运行, 2=报警)"""
        return self.write_holding_register(0, status)
    
    def set_alarm_enable(self, enabled):
        """设置报警使能"""
        return self.write_holding_register(1, 1 if enabled else 0)
    
    def set_sensor_interval(self, seconds):
        """设置传感器间隔"""
        return self.write_holding_register(2, seconds)
    
    def control_red_light(self, on):
        """控制红灯"""
        return self.write_coil(0, on)
    
    def control_green_light(self, on):
        """控制绿灯"""
        return self.write_coil(1, on)
    
    def control_blue_light(self, on):
        """控制蓝灯"""
        return self.write_coil(2, on)
    
    def control_buzzer(self, on):
        """控制蜂鸣器"""
        return self.write_coil(3, on)
    def control_indicator(self, on):
        """控制指示灯"""
        return self.write_coil(4, on)
