"""
ModBus_rtu Master 和 Server 
"""
import serial
import struct
import time
import threading
from typing import Optional, List
from . import defines
from .modbus_frame import ModbusCRC


class RtuMaster:
    """
    ModBus RTU 主站(客户端)
    用法与 modbus-tk 的 RtuMaster 相同
    """
    
    def __init__(self, serial_port):
        """
        初始化 RTU Master
        
        Args:
            serial_port: pyserial.Serial 对象
        """
        if isinstance(serial_port, str):
            # 如果传入的是串口名称，自动创建 Serial 对象
            self._serial = serial.Serial(
                port=serial_port,
                baudrate=9600,
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=1.0
            )
        else:
            self._serial = serial_port
        
        self._is_opened = self._serial.is_open
        self._timeout = self._serial.timeout if self._serial.timeout else 1.0
        
        # RTU 时间参数(基于波特率计算)
        self._t0 = self._calculate_t0(self._serial.baudrate)
    
    def _calculate_t0(self, baudrate):
        """计算字符间超时时间"""
        # t0 = 11 bits / baudrate (1 起始位 + 8 数据位 + 1 校验位 + 1 停止位)
        if baudrate > 19200:
            return 0.00175  # 1.75ms for high baudrates
        else:
            return 11.0 / baudrate
    
    def set_timeout(self, timeout_in_sec):
        """设置超时时间"""
        self._timeout = timeout_in_sec
        self._serial.timeout = timeout_in_sec
    
    def open(self):
        """打开串口"""
        if not self._is_opened:
            if not self._serial.is_open:
                self._serial.open()
            self._is_opened = True
    
    def close(self):
        """关闭串口"""
        if self._is_opened and self._serial.is_open:
            self._serial.close()
            self._is_opened = False
    
    def __del__(self):
        """析构函数"""
        self.close()
    
    def _build_request(self, slave, function_code, data):
        """构建 RTU 请求帧"""
        # RTU 帧 = 从站地址 + 功能码 + 数据 + CRC
        frame = struct.pack('BB', slave, function_code) + data
        crc = ModbusCRC.calculate_crc(frame)
        return frame + struct.pack('<H', crc)  # 注意：CRC 是小端序
    
    def _parse_response(self, response, slave):
        """解析 RTU 响应帧"""
        if len(response) < 5:  # 至少：地址(1) + 功能码(1) + 数据(1) + CRC(2)
            return None
        
        # 检查从站地址
        resp_slave = response[0]
        if resp_slave != slave:
            return None
        
        # 检查 CRC
        crc_received = struct.unpack('<H', response[-2:])[0]
        crc_calculated = ModbusCRC.calculate_crc(response[:-2])
        if crc_received != crc_calculated:
            print(f"CRC error: received={crc_received:04X}, calculated={crc_calculated:04X}")
            return None
        
        # 返回功能码和数据
        function_code = response[1]
        data = response[2:-2]
        return function_code, data
    
    def _send_receive(self, request, expected_length=-1):
        """发送请求并接收响应"""
        try:
            self.open()
            
            # 清空缓冲区
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            
            # 发送请求
            self._serial.write(request)
            
            # 等待帧间延迟
            time.sleep(3.5 * self._t0)
            
            # 接收响应
            response = b''
            start_time = time.time()
            
            while time.time() - start_time < self._timeout:
                if self._serial.in_waiting > 0:
                    chunk = self._serial.read(self._serial.in_waiting)
                    response += chunk
                    
                    # 检查是否接收完整
                    if len(response) >= 5:  # 最小帧长度
                        # 等待字符间超时
                        time.sleep(1.5 * self._t0)
                        if self._serial.in_waiting == 0:
                            # 没有更多数据，认为帧接收完毕
                            break
                else:
                    time.sleep(0.001)
            
            return response if len(response) >= 5 else None
            
        except Exception as e:
            print(f"Communication error: {e}")
            return None
    
    def execute(self, slave, function_code, starting_address, quantity_of_x=0,
                output_value=0, data_format='', expected_length=-1):
        """
        执行 ModBus 命令(与 modbus-tk 兼容的接口)
        
        Args:
            slave: 从站地址(1-247)
            function_code: 功能码
            starting_address: 起始地址
            quantity_of_x: 读取数量
            output_value: 写入值(单个值或列表)
            data_format: 数据格式(暂不支持)
            expected_length: 期望长度(暂不使用)
            
        Returns:
            读操作返回数据元组，写操作返回(地址, 数量)元组
        """
        # 读线圈
        if function_code == defines.READ_COILS:
            data = struct.pack('>HH', starting_address, quantity_of_x)
            request = self._build_request(slave, function_code, data)
            response = self._send_receive(request)
            
            if response:
                result = self._parse_response(response, slave)
                if result:
                    func_code, resp_data = result
                    if func_code & 0x80:
                        print(f"Exception response: {resp_data[0] if resp_data else 0}")
                        return tuple()
                    
                    if len(resp_data) >= 1:
                        byte_count = resp_data[0]
                        coil_bytes = resp_data[1:1+byte_count]
                        coils = []
                        for byte in coil_bytes:
                            for bit in range(8):
                                coils.append(bool((byte >> bit) & 1))
                        return tuple(coils[:quantity_of_x])
        
        # 读保持寄存器
        elif function_code == defines.READ_HOLDING_REGISTERS:
            data = struct.pack('>HH', starting_address, quantity_of_x)
            request = self._build_request(slave, function_code, data)
            response = self._send_receive(request)
            
            if response:
                result = self._parse_response(response, slave)
                if result:
                    func_code, resp_data = result
                    if func_code & 0x80:
                        print(f"Exception response: {resp_data[0] if resp_data else 0}")
                        return tuple()
                    
                    if len(resp_data) >= 1:
                        byte_count = resp_data[0]
                        register_data = resp_data[1:1+byte_count]
                        registers = []
                        for i in range(0, byte_count, 2):
                            value = struct.unpack('>H', register_data[i:i+2])[0]
                            registers.append(value)
                        return tuple(registers[:quantity_of_x])
        
        # 读输入寄存器
        elif function_code == defines.READ_INPUT_REGISTERS:
            data = struct.pack('>HH', starting_address, quantity_of_x)
            request = self._build_request(slave, function_code, data)
            response = self._send_receive(request)
            
            if response:
                result = self._parse_response(response, slave)
                if result:
                    func_code, resp_data = result
                    if func_code & 0x80:
                        return tuple()
                    
                    if len(resp_data) >= 1:
                        byte_count = resp_data[0]
                        register_data = resp_data[1:1+byte_count]
                        registers = []
                        for i in range(0, byte_count, 2):
                            value = struct.unpack('>H', register_data[i:i+2])[0]
                            registers.append(value)
                        return tuple(registers[:quantity_of_x])
        
        # 读离散输入
        elif function_code == defines.READ_DISCRETE_INPUTS:
            data = struct.pack('>HH', starting_address, quantity_of_x)
            request = self._build_request(slave, function_code, data)
            response = self._send_receive(request)
            
            if response:
                result = self._parse_response(response, slave)
                if result:
                    func_code, resp_data = result
                    if func_code & 0x80:
                        return tuple()
                    
                    if len(resp_data) >= 1:
                        byte_count = resp_data[0]
                        input_bytes = resp_data[1:1+byte_count]
                        inputs = []
                        for byte in input_bytes:
                            for bit in range(8):
                                inputs.append(bool((byte >> bit) & 1))
                        return tuple(inputs[:quantity_of_x])
        
        # 写单个线圈
        elif function_code == defines.WRITE_SINGLE_COIL:
            value = 0xFF00 if output_value else 0x0000
            data = struct.pack('>HH', starting_address, value)
            request = self._build_request(slave, function_code, data)
            response = self._send_receive(request)
            
            if response:
                result = self._parse_response(response, slave)
                if result:
                    func_code, resp_data = result
                    if func_code & 0x80:
                        return tuple()
                    
                    if len(resp_data) >= 4:
                        addr, val = struct.unpack('>HH', resp_data[:4])
                        return (addr, val)
        
        # 写单个寄存器
        elif function_code == defines.WRITE_SINGLE_REGISTER:
            data = struct.pack('>HH', starting_address, output_value & 0xFFFF)
            request = self._build_request(slave, function_code, data)
            response = self._send_receive(request)
            
            if response:
                result = self._parse_response(response, slave)
                if result:
                    func_code, resp_data = result
                    if func_code & 0x80:
                        return tuple()
                    
                    if len(resp_data) >= 4:
                        addr, val = struct.unpack('>HH', resp_data[:4])
                        return (addr, val)
        
        # 写多个线圈
        elif function_code == defines.WRITE_MULTIPLE_COILS:
            if not isinstance(output_value, (list, tuple)):
                output_value = [output_value]
            
            byte_count = (len(output_value) + 7) // 8
            coil_bytes = bytearray(byte_count)
            for i, status in enumerate(output_value):
                if status:
                    byte_index = i // 8
                    bit_index = i % 8
                    coil_bytes[byte_index] |= (1 << bit_index)
            
            data = struct.pack('>HHB', starting_address, len(output_value), byte_count) + bytes(coil_bytes)
            request = self._build_request(slave, function_code, data)
            response = self._send_receive(request)
            
            if response:
                result = self._parse_response(response, slave)
                if result:
                    func_code, resp_data = result
                    if func_code & 0x80:
                        return tuple()
                    
                    if len(resp_data) >= 4:
                        addr, qty = struct.unpack('>HH', resp_data[:4])
                        return (addr, qty)
        
        # 写多个寄存器
        elif function_code == defines.WRITE_MULTIPLE_REGISTERS:
            if not isinstance(output_value, (list, tuple)):
                output_value = [output_value]
            
            byte_count = len(output_value) * 2
            data = struct.pack('>HHB', starting_address, len(output_value), byte_count)
            for value in output_value:
                data += struct.pack('>H', value & 0xFFFF)
            
            request = self._build_request(slave, function_code, data)
            response = self._send_receive(request)
            
            if response:
                result = self._parse_response(response, slave)
                if result:
                    func_code, resp_data = result
                    if func_code & 0x80:
                        return tuple()
                    
                    if len(resp_data) >= 4:
                        addr, qty = struct.unpack('>HH', resp_data[:4])
                        return (addr, qty)
        
        return tuple()


class RtuServer:
    """
    ModBus RTU 服务器(从站)
    用法与 modbus-tk 的 RtuServer 相同
    """
    
    def __init__(self, serial_port, slave_id=1):
        """
        初始化 RTU Server
        
        Args:
            serial_port: pyserial.Serial 对象或串口名称
            slave_id: 默认从站地址
        """
        if isinstance(serial_port, str):
            self._serial = serial.Serial(
                port=serial_port,
                baudrate=9600,
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=0.1
            )
        else:
            self._serial = serial_port
        
        self._is_running = False
        self._slaves = {}
        self._server_thread = None
        
        # RTU 时间参数
        self._t0 = self._calculate_t0(self._serial.baudrate)
        
        # 添加默认从站
        if slave_id > 0:
            self.add_slave(slave_id)
    
    def _calculate_t0(self, baudrate):
        """计算字符间超时时间"""
        if baudrate > 19200:
            return 0.00175
        else:
            return 11.0 / baudrate
    
    def add_slave(self, slave_id):
        """添加从站"""
        try:
            from .modbus_tcp import Slave  # 复用 TCP 的 Slave 类
        except ImportError:
            from modbus_tcp import Slave
        slave = Slave(slave_id)
        self._slaves[slave_id] = slave
        return slave
    
    def remove_slave(self, slave_id):
        """删除从站"""
        if slave_id in self._slaves:
            del self._slaves[slave_id]
    
    def get_slave(self, slave_id):
        """获取从站对象"""
        return self._slaves.get(slave_id)
    
    def start(self):
        """启动服务器"""
        if self._is_running:
            return
        
        if not self._serial.is_open:
            self._serial.open()
        
        self._is_running = True
        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()
    
    def stop(self):
        """停止服务器"""
        self._is_running = False
        if self._server_thread:
            self._server_thread.join(timeout=2.0)
        
        if self._serial.is_open:
            self._serial.close()
    
    def _run_server(self):
        """服务器主循环"""
        buffer = b''
        last_byte_time = time.time()
        
        while self._is_running:
            try:
                # 检查是否有数据
                if self._serial.in_waiting > 0:
                    # 读取数据
                    data = self._serial.read(self._serial.in_waiting)
                    buffer += data
                    last_byte_time = time.time()
                else:
                    # 检查帧间延迟
                    if buffer and (time.time() - last_byte_time) > 3.5 * self._t0:
                        # 一帧接收完毕，处理请求
                        response = self._process_request(buffer)
                        if response:
                            # 发送响应前等待
                            time.sleep(3.5 * self._t0)
                            self._serial.write(response)
                        
                        buffer = b''
                    
                    time.sleep(0.001)
            
            except Exception as e:
                print(f"RTU Server error: {e}")
                buffer = b''
    
    def _process_request(self, request: bytes) -> Optional[bytes]:
        """处理 RTU 请求"""
        if len(request) < 5:  # 最小帧：地址(1) + 功能码(1) + 数据(1) + CRC(2)
            return None
        
        # 解析帧
        slave_addr = request[0]
        function_code = request[1]
        data = request[2:-2]
        crc_received = struct.unpack('<H', request[-2:])[0]
        
        # 验证 CRC
        crc_calculated = ModbusCRC.calculate_crc(request[:-2])
        if crc_received != crc_calculated:
            return None
        
        # 查找从站
        slave = self._slaves.get(slave_addr)
        if not slave:
            # 广播地址(0)也忽略
            return None
        
        # 处理请求
        try:
            response_data = None
            
            if function_code == defines.READ_COILS:
                if len(data) >= 4:
                    start_addr, quantity = struct.unpack('>HH', data[:4])
                    values = slave._get_values_by_type(defines.COILS, start_addr, quantity)
                    
                    byte_count = (quantity + 7) // 8
                    coil_bytes = bytearray(byte_count)
                    for i, status in enumerate(values):
                        if status:
                            byte_index = i // 8
                            bit_index = i % 8
                            coil_bytes[byte_index] |= (1 << bit_index)
                    
                    response_data = struct.pack('B', byte_count) + bytes(coil_bytes)
            
            elif function_code == defines.READ_DISCRETE_INPUTS:
                if len(data) >= 4:
                    start_addr, quantity = struct.unpack('>HH', data[:4])
                    values = slave._get_values_by_type(defines.DISCRETE_INPUTS, start_addr, quantity)
                    
                    byte_count = (quantity + 7) // 8
                    input_bytes = bytearray(byte_count)
                    for i, status in enumerate(values):
                        if status:
                            byte_index = i // 8
                            bit_index = i % 8
                            input_bytes[byte_index] |= (1 << bit_index)
                    
                    response_data = struct.pack('B', byte_count) + bytes(input_bytes)
            
            elif function_code == defines.READ_HOLDING_REGISTERS:
                if len(data) >= 4:
                    start_addr, quantity = struct.unpack('>HH', data[:4])
                    values = slave._get_values_by_type(defines.HOLDING_REGISTERS, start_addr, quantity)
                    
                    byte_count = len(values) * 2
                    response_data = struct.pack('B', byte_count)
                    for value in values:
                        response_data += struct.pack('>H', value)
            
            elif function_code == defines.READ_INPUT_REGISTERS:
                if len(data) >= 4:
                    start_addr, quantity = struct.unpack('>HH', data[:4])
                    values = slave._get_values_by_type(defines.INPUT_REGISTERS, start_addr, quantity)
                    
                    byte_count = len(values) * 2
                    response_data = struct.pack('B', byte_count)
                    for value in values:
                        response_data += struct.pack('>H', value)
            
            elif function_code == defines.WRITE_SINGLE_COIL:
                if len(data) >= 4:
                    address, coil_value = struct.unpack('>HH', data[:4])
                    if coil_value in [0x0000, 0xFF00]:
                        value = (coil_value == 0xFF00)
                        slave._set_values_by_type(defines.COILS, address, [value])
                        response_data = data[:4]  # 回显
            
            elif function_code == defines.WRITE_SINGLE_REGISTER:
                if len(data) >= 4:
                    address, value = struct.unpack('>HH', data[:4])
                    slave._set_values_by_type(defines.HOLDING_REGISTERS, address, [value])
                    response_data = data[:4]  # 回显
            
            elif function_code == defines.WRITE_MULTIPLE_COILS:
                if len(data) >= 5:
                    start_addr, quantity, byte_count = struct.unpack('>HHB', data[:5])
                    coil_bytes = data[5:5+byte_count]
                    
                    values = []
                    for byte in coil_bytes:
                        for bit in range(8):
                            if len(values) < quantity:
                                values.append(bool((byte >> bit) & 1))
                    
                    slave._set_values_by_type(defines.COILS, start_addr, values)
                    response_data = struct.pack('>HH', start_addr, quantity)
            
            elif function_code == defines.WRITE_MULTIPLE_REGISTERS:
                if len(data) >= 5:
                    start_addr, quantity, byte_count = struct.unpack('>HHB', data[:5])
                    register_data = data[5:5+byte_count]
                    
                    values = []
                    for i in range(0, byte_count, 2):
                        value = struct.unpack('>H', register_data[i:i+2])[0]
                        values.append(value)
                    
                    slave._set_values_by_type(defines.HOLDING_REGISTERS, start_addr, values)
                    response_data = struct.pack('>HH', start_addr, quantity)
            
            else:
                # 不支持的功能码
                response_data = struct.pack('B', defines.ILLEGAL_FUNCTION)
                function_code |= 0x80
            
            if response_data:
                # 构建响应帧
                frame = struct.pack('BB', slave_addr, function_code) + response_data
                crc = ModbusCRC.calculate_crc(frame)
                return frame + struct.pack('<H', crc)
        
        except Exception as e:
            print(f"Error processing request: {e}")
            # 返回异常响应
            frame = struct.pack('BBB', slave_addr, function_code | 0x80, defines.SLAVE_DEVICE_FAILURE)
            crc = ModbusCRC.calculate_crc(frame)
            return frame + struct.pack('<H', crc)
        
        return None
