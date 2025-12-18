"""
ModBus_tcp Master 和 Server 实现
"""
import socket
import struct
import threading
import time
from typing import Optional, List, Tuple
from . import defines
from .modbus_frame import ModbusTCPFrame
class TcpMaster:
    """
    ModBus TCP 主站
    """
    def __init__(self, host='127.0.0.1', port=502, timeout_in_sec=5.0):
        """
        初始化 TCP Master
        
        Args:
            host: 服务器地址
            port: 服务器端口，默认 502
            timeout_in_sec: 超时时间(秒)
        """
        self._host = host
        self._port = port
        self._timeout = timeout_in_sec
        self._sock = None
        self._transaction_id = 0
        self._is_opened = False
        self._lock = threading.Lock()
    
    def set_timeout(self, timeout_in_sec):
        """设置超时时间"""
        self._timeout = timeout_in_sec
        if self._sock:
            try:
                self._sock.settimeout(timeout_in_sec)
            except:
                pass
    
    def open(self):
        """打开连接"""
        with self._lock:
            if self._is_opened and self._sock:
                # 测试连接是否有效
                try:
                    self._sock.getpeername()
                    return
                except:
                    self.close()
            
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(self._timeout)
                self._sock.connect((self._host, self._port))
                self._is_opened = True
                print(f"连接成功: {self._host}:{self._port}")
            except socket.timeout:
                self._is_opened = False
                self._sock = None
                raise Exception(f"连接超时: {self._host}:{self._port}")
            except ConnectionRefusedError:
                self._is_opened = False
                self._sock = None
                raise Exception(f"连接被拒绝: {self._host}:{self._port}，请确认服务器已启动")
            except Exception as e:
                self._is_opened = False
                self._sock = None
                raise Exception(f"连接失败: {self._host}:{self._port}, 错误: {e}")
    
    def close(self):
        """关闭连接"""
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except:
                    pass
                self._sock = None
            self._is_opened = False
    
    def __del__(self):
        """析构函数"""
        self.close()
    
    def _get_transaction_id(self):
        """获取事务ID"""
        self._transaction_id = (self._transaction_id + 1) % 65536
        return self._transaction_id
    
    def _send_receive(self, request: bytes, retry_count=3) -> Optional[bytes]:
        """发送请求并接收响应"""
        last_error = None
        
        for attempt in range(retry_count):
            try:
                self.open()
                
                # 发送请求
                self._sock.sendall(request)
                
                # 接收MBAP头(7字节)
                header = b''
                while len(header) < 7:
                    chunk = self._sock.recv(7 - len(header))
                    if not chunk:
                        raise Exception("连接已关闭")
                    header += chunk
                
                # 解析长度字段
                length = struct.unpack('>H', header[4:6])[0]
                
                # 接收剩余数据 (length - 1字节，因为unit_id已在header中)
                remaining = length - 1
                data = header
                while remaining > 0:
                    chunk = self._sock.recv(remaining)
                    if not chunk:
                        raise Exception("接收数据不完整")
                    data += chunk
                    remaining -= len(chunk)
                
                return data
                
            except socket.timeout:
                last_error = "通信超时"
                print(f"尝试 {attempt + 1}/{retry_count}: {last_error}")
                self.close()
                if attempt < retry_count - 1:
                    time.sleep(0.5)
            except Exception as e:
                last_error = str(e)
                print(f"尝试 {attempt + 1}/{retry_count}: 通信错误: {e}")
                self.close()
                if attempt < retry_count - 1:
                    time.sleep(0.5)
        
        raise Exception(f"通信失败，已重试{retry_count}次: {last_error}")
    
    def execute(self, slave, function_code, starting_address, quantity_of_x=0, 
                output_value=0, data_format='', expected_length=-1):
        """
        执行 ModBus 命令(与 modbus-tk 兼容的接口)
        
        Args:
            slave: 从站地址
            function_code: 功能码
            starting_address: 起始地址
            quantity_of_x: 读取数量
            output_value: 写入值(单个值或列表)
            data_format: 数据格式(暂不支持)
            expected_length: 期望长度(暂不使用)
            
        Returns:
            读操作返回数据元组，写操作返回(地址, 数量)元组
        """
        try:
            transaction_id = self._get_transaction_id()
            
            # 读线圈
            if function_code == defines.READ_COILS:
                request = ModbusTCPFrame.build_read_coils_request(
                    transaction_id, slave, starting_address, quantity_of_x
                )
                response = self._send_receive(request)
                frame = ModbusTCPFrame.parse_frame(response)
                if not frame:
                    raise Exception("响应帧解析失败")
                if frame.function_code & 0x80:
                    raise Exception(f"ModBus异常: 0x{frame.data[0]:02X}" if frame.data else "未知错误")
                
                coils = ModbusTCPFrame.parse_read_coils_response(frame)
                if coils is None:
                    raise Exception("解析线圈数据失败")
                return tuple(coils[:quantity_of_x])
            
            # 读保持寄存器
            elif function_code == defines.READ_HOLDING_REGISTERS:
                request = ModbusTCPFrame.build_read_holding_registers_request(
                    transaction_id, slave, starting_address, quantity_of_x
                )
                response = self._send_receive(request)
                frame = ModbusTCPFrame.parse_frame(response)
                if not frame:
                    raise Exception("响应帧解析失败")
                if frame.function_code & 0x80:
                    raise Exception(f"ModBus异常: 0x{frame.data[0]:02X}" if frame.data else "未知错误")
                
                registers = ModbusTCPFrame.parse_read_holding_registers_response(frame)
                if registers is None:
                    raise Exception("解析寄存器数据失败")
                return tuple(registers[:quantity_of_x])
            
            # 读输入寄存器(功能码 0x04)
            elif function_code == defines.READ_INPUT_REGISTERS:
                data = struct.pack('>HH', starting_address, quantity_of_x)
                request = ModbusTCPFrame.build_request(transaction_id, slave, function_code, data)
                response = self._send_receive(request)
                frame = ModbusTCPFrame.parse_frame(response)
                if not frame:
                    raise Exception("响应帧解析失败")
                if frame.function_code & 0x80:
                    raise Exception(f"ModBus异常: 0x{frame.data[0]:02X}" if frame.data else "未知错误")
                
                if not frame.data or len(frame.data) < 1:
                    raise Exception("响应数据为空")
                byte_count = frame.data[0]
                register_data = frame.data[1:1+byte_count]
                registers = []
                for i in range(0, byte_count, 2):
                    if i + 1 < len(register_data):
                        value = struct.unpack('>H', register_data[i:i+2])[0]
                        registers.append(value)
                return tuple(registers[:quantity_of_x])
            
            # 读离散输入(功能码 0x02)
            elif function_code == defines.READ_DISCRETE_INPUTS:
                data = struct.pack('>HH', starting_address, quantity_of_x)
                request = ModbusTCPFrame.build_request(transaction_id, slave, function_code, data)
                response = self._send_receive(request)
                frame = ModbusTCPFrame.parse_frame(response)
                if not frame:
                    raise Exception("响应帧解析失败")
                if frame.function_code & 0x80:
                    raise Exception(f"ModBus异常: 0x{frame.data[0]:02X}" if frame.data else "未知错误")
                
                if not frame.data or len(frame.data) < 1:
                    raise Exception("响应数据为空")
                byte_count = frame.data[0]
                input_bytes = frame.data[1:1+byte_count]
                inputs = []
                for byte in input_bytes:
                    for bit in range(8):
                        inputs.append(bool((byte >> bit) & 1))
                return tuple(inputs[:quantity_of_x])
            
            # 写单个线圈
            elif function_code == defines.WRITE_SINGLE_COIL:
                value = bool(output_value)
                request = ModbusTCPFrame.build_write_single_coil_request(
                    transaction_id, slave, starting_address, value
                )
                response = self._send_receive(request)
                frame = ModbusTCPFrame.parse_frame(response)
                if not frame:
                    raise Exception("响应帧解析失败")
                if frame.function_code & 0x80:
                    raise Exception(f"ModBus异常: 0x{frame.data[0]:02X}" if frame.data else "未知错误")
                
                if len(frame.data) >= 4:
                    addr, val = struct.unpack('>HH', frame.data[:4])
                    return (addr, val)
                return (starting_address, 0xFF00 if value else 0x0000)
            
            # 写单个寄存器
            elif function_code == defines.WRITE_SINGLE_REGISTER:
                data = struct.pack('>HH', starting_address, output_value & 0xFFFF)
                request = ModbusTCPFrame.build_request(transaction_id, slave, function_code, data)
                response = self._send_receive(request)
                frame = ModbusTCPFrame.parse_frame(response)
                if not frame:
                    raise Exception("响应帧解析失败")
                if frame.function_code & 0x80:
                    raise Exception(f"ModBus异常: 0x{frame.data[0]:02X}" if frame.data else "未知错误")
                
                if len(frame.data) >= 4:
                    addr, val = struct.unpack('>HH', frame.data[:4])
                    return (addr, val)
                return (starting_address, output_value & 0xFFFF)
            
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
                request = ModbusTCPFrame.build_request(transaction_id, slave, function_code, data)
                response = self._send_receive(request)
                frame = ModbusTCPFrame.parse_frame(response)
                if not frame:
                    raise Exception("响应帧解析失败")
                if frame.function_code & 0x80:
                    raise Exception(f"ModBus异常: 0x{frame.data[0]:02X}" if frame.data else "未知错误")
                
                if len(frame.data) >= 4:
                    addr, qty = struct.unpack('>HH', frame.data[:4])
                    return (addr, qty)
                return (starting_address, len(output_value))
            
            # 写多个寄存器
            elif function_code == defines.WRITE_MULTIPLE_REGISTERS:
                if not isinstance(output_value, (list, tuple)):
                    output_value = [output_value]
                
                byte_count = len(output_value) * 2
                data = struct.pack('>HHB', starting_address, len(output_value), byte_count)
                for value in output_value:
                    data += struct.pack('>H', value & 0xFFFF)
                
                request = ModbusTCPFrame.build_request(transaction_id, slave, function_code, data)
                response = self._send_receive(request)
                frame = ModbusTCPFrame.parse_frame(response)
                if not frame:
                    raise Exception("响应帧解析失败")
                if frame.function_code & 0x80:
                    raise Exception(f"ModBus异常: 0x{frame.data[0]:02X}" if frame.data else "未知错误")
                
                if len(frame.data) >= 4:
                    addr, qty = struct.unpack('>HH', frame.data[:4])
                    return (addr, qty)
                return (starting_address, len(output_value))
            
            raise Exception(f"不支持的功能码: 0x{function_code:02X}")
            
        except Exception as e:
            raise Exception(f"执行ModBus命令失败: {e}")


class Databank:
    """
    数据存储区(与 modbus-tk 兼容)
    存储线圈、离散输入、输入寄存器、保持寄存器
    """
    
    def __init__(self, block_type, starting_address, size):
        """
        初始化数据块
        
        Args:
            block_type: 数据类型(COILS, DISCRETE_INPUTS, INPUT_REGISTERS, HOLDING_REGISTERS)
            starting_address: 起始地址
            size: 数据块大小
        """
        self.block_type = block_type
        self.starting_address = starting_address
        self.size = size
        
        if block_type in [defines.COILS, defines.DISCRETE_INPUTS]:
            self.data = [False] * size
        else:
            self.data = [0] * size
    
    def set_values(self, address, values):
        """
        设置值
        
        Args:
            address: 起始地址(相对于块起始地址)
            values: 值列表
        """
        if not isinstance(values, (list, tuple)):
            values = [values]
        
        for i, value in enumerate(values):
            idx = address - self.starting_address + i
            if 0 <= idx < self.size:
                if self.block_type in [defines.COILS, defines.DISCRETE_INPUTS]:
                    self.data[idx] = bool(value)
                else:
                    self.data[idx] = value & 0xFFFF
    
    def get_values(self, address, count=1):
        """
        获取值
        
        Args:
            address: 起始地址(相对于块起始地址)
            count: 数量
            
        Returns:
            值列表
        """
        result = []
        for i in range(count):
            idx = address - self.starting_address + i
            if 0 <= idx < self.size:
                result.append(self.data[idx])
            else:
                if self.block_type in [defines.COILS, defines.DISCRETE_INPUTS]:
                    result.append(False)
                else:
                    result.append(0)
        return result


class Slave:
    """
    ModBus 从站(与 modbus-tk 兼容)
    """
    
    def __init__(self, slave_id):
        """
        初始化从站
        
        Args:
            slave_id: 从站地址
        """
        self.slave_id = slave_id
        self.blocks = {}  # 数据块字典 {name: Databank}
    
    def add_block(self, block_name, block_type, starting_address, size):
        """
        添加数据块
        
        Args:
            block_name: 块名称
            block_type: 块类型
            starting_address: 起始地址
            size: 块大小
        """
        self.blocks[block_name] = Databank(block_type, starting_address, size)
    
    def remove_block(self, block_name):
        """删除数据块"""
        if block_name in self.blocks:
            del self.blocks[block_name]
    
    def remove_all_blocks(self):
        """删除所有数据块"""
        self.blocks.clear()
    
    def set_values(self, block_name, address, values):
        """设置数据块的值"""
        if block_name in self.blocks:
            self.blocks[block_name].set_values(address, values)
    
    def get_values(self, block_name, address, count=1):
        """获取数据块的值"""
        if block_name in self.blocks:
            return self.blocks[block_name].get_values(address, count)
        return []
    
    def _find_block(self, block_type, address):
        """根据类型和地址查找数据块"""
        for block in self.blocks.values():
            if block.block_type == block_type:
                if block.starting_address <= address < block.starting_address + block.size:
                    return block
        return None
    
    def _get_values_by_type(self, block_type, address, count):
        """按类型获取值"""
        block = self._find_block(block_type, address)
        if block:
            return block.get_values(address, count)
        return [False] * count if block_type in [defines.COILS, defines.DISCRETE_INPUTS] else [0] * count
    
    def _set_values_by_type(self, block_type, address, values):
        """按类型设置值"""
        block = self._find_block(block_type, address)
        if block:
            block.set_values(address, values)
            return True
        return False


class TcpServer:
    """
    ModBus TCP 服务器(从站)
    用法与 modbus-tk 的 TcpServer 相同
    """
    
    def __init__(self, port=502, address=''):
        """
        初始化 TCP Server
        
        Args:
            port: 监听端口
            address: 绑定地址，默认监听所有接口
        """
        self._port = port
        self._address = address
        self._sock = None
        self._is_running = False
        self._slaves = {}  # {slave_id: Slave}
        self._server_thread = None
        self._client_threads = []
    
    def add_slave(self, slave_id):
        """
        添加从站
        
        Args:
            slave_id: 从站地址
            
        Returns:
            Slave 对象
        """
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
        
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self._address, self._port))
            self._sock.listen(5)
            self._sock.settimeout(1.0)
            self._is_running = True
            
            print(f"ModBus TCP服务器启动成功: {self._address or '0.0.0.0'}:{self._port}")
            
            self._server_thread = threading.Thread(target=self._run_server, daemon=True)
            self._server_thread.start()
        except Exception as e:
            print(f"启动服务器失败: {e}")
            self._is_running = False
            if self._sock:
                try:
                    self._sock.close()
                except:
                    pass
                self._sock = None
            raise
    
    def stop(self):
        """停止服务器"""
        print("正在停止ModBus TCP服务器...")
        self._is_running = False
        if self._sock:
            try:
                self._sock.close()
            except:
                pass
            self._sock = None
        print("ModBus TCP服务器已停止")
    
    def _run_server(self):
        """服务器主循环"""
        while self._is_running:
            try:
                client_sock, addr = self._sock.accept()
                print(f"新客户端连接: {addr}")
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr),
                    daemon=True
                )
                client_thread.start()
                self._client_threads.append(client_thread)
            except socket.timeout:
                continue
            except Exception as e:
                if self._is_running:
                    print(f"服务器错误: {e}")
    
    def _handle_client(self, client_sock, addr):
        """处理客户端连接"""
        try:
            client_sock.settimeout(30.0)  # 30秒超时
            
            while self._is_running:
                try:
                    # 接收MBAP头(7字节)
                    header = b''
                    while len(header) < 7:
                        chunk = client_sock.recv(7 - len(header))
                        if not chunk:
                            return
                        header += chunk
                    
                    # 解析长度
                    length = struct.unpack('>H', header[4:6])[0]
                    
                    # 接收PDU (length - 1字节，因为unit_id已在header中)
                    remaining = length - 1
                    pdu = b''
                    while remaining > 0:
                        chunk = client_sock.recv(remaining)
                        if not chunk:
                            return
                        pdu += chunk
                        remaining -= len(chunk)
                    
                    # 完整的请求
                    request = header + pdu
                    
                    # 处理请求
                    response = self._process_request(request)
                    if response:
                        client_sock.sendall(response)
                
                except socket.timeout:
                    print(f"客户端 {addr} 超时")
                    break
                except Exception as e:
                    print(f"处理客户端 {addr} 请求时出错: {e}")
                    break
        
        finally:
            try:
                client_sock.close()
            except:
                pass
            print(f"客户端 {addr} 断开连接")
    
    def _process_request(self, request: bytes) -> Optional[bytes]:
        """处理 ModBus 请求"""
        frame = ModbusTCPFrame.parse_frame(request)
        if not frame:
            return None
        
        # 查找从站
        slave = self._slaves.get(frame.unit_id)
        if not slave:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.SLAVE_DEVICE_FAILURE
            )
        
        # 根据功能码处理
        try:
            if frame.function_code == defines.READ_COILS:
                return self._handle_read_coils(frame, slave)
            elif frame.function_code == defines.READ_DISCRETE_INPUTS:
                return self._handle_read_discrete_inputs(frame, slave)
            elif frame.function_code == defines.READ_HOLDING_REGISTERS:
                return self._handle_read_holding_registers(frame, slave)
            elif frame.function_code == defines.READ_INPUT_REGISTERS:
                return self._handle_read_input_registers(frame, slave)
            elif frame.function_code == defines.WRITE_SINGLE_COIL:
                return self._handle_write_single_coil(frame, slave)
            elif frame.function_code == defines.WRITE_SINGLE_REGISTER:
                return self._handle_write_single_register(frame, slave)
            elif frame.function_code == defines.WRITE_MULTIPLE_COILS:
                return self._handle_write_multiple_coils(frame, slave)
            elif frame.function_code == defines.WRITE_MULTIPLE_REGISTERS:
                return self._handle_write_multiple_registers(frame, slave)
            else:
                return ModbusTCPFrame.build_error_response(
                    frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_FUNCTION
                )
        except Exception as e:
            print(f"Error processing request: {e}")
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.SLAVE_DEVICE_FAILURE
            )
    
    def _handle_read_coils(self, frame: ModbusTCPFrame, slave: Slave) -> bytes:
        """处理读线圈"""
        if len(frame.data) < 4:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_DATA_VALUE
            )
        
        start_addr, quantity = struct.unpack('>HH', frame.data[:4])
        values = slave._get_values_by_type(defines.COILS, start_addr, quantity)
        return ModbusTCPFrame.build_read_coils_response(frame.transaction_id, frame.unit_id, values)
    
    def _handle_read_discrete_inputs(self, frame: ModbusTCPFrame, slave: Slave) -> bytes:
        """处理读离散输入"""
        if len(frame.data) < 4:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_DATA_VALUE
            )
        
        start_addr, quantity = struct.unpack('>HH', frame.data[:4])
        values = slave._get_values_by_type(defines.DISCRETE_INPUTS, start_addr, quantity)
        
        # 构建响应
        byte_count = (quantity + 7) // 8
        input_bytes = bytearray(byte_count)
        for i, status in enumerate(values):
            if status:
                byte_index = i // 8
                bit_index = i % 8
                input_bytes[byte_index] |= (1 << bit_index)
        
        data = struct.pack('B', byte_count) + bytes(input_bytes)
        return ModbusTCPFrame.build_request(frame.transaction_id, frame.unit_id, frame.function_code, data)
    
    def _handle_read_holding_registers(self, frame: ModbusTCPFrame, slave: Slave) -> bytes:
        """处理读保持寄存器"""
        if len(frame.data) < 4:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_DATA_VALUE
            )
        
        start_addr, quantity = struct.unpack('>HH', frame.data[:4])
        values = slave._get_values_by_type(defines.HOLDING_REGISTERS, start_addr, quantity)
        return ModbusTCPFrame.build_read_holding_registers_response(frame.transaction_id, frame.unit_id, values)
    
    def _handle_read_input_registers(self, frame: ModbusTCPFrame, slave: Slave) -> bytes:
        """处理读输入寄存器"""
        if len(frame.data) < 4:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_DATA_VALUE
            )
        
        start_addr, quantity = struct.unpack('>HH', frame.data[:4])
        values = slave._get_values_by_type(defines.INPUT_REGISTERS, start_addr, quantity)
        
        byte_count = len(values) * 2
        data = struct.pack('B', byte_count)
        for value in values:
            data += struct.pack('>H', value)
        
        return ModbusTCPFrame.build_request(frame.transaction_id, frame.unit_id, frame.function_code, data)
    
    def _handle_write_single_coil(self, frame: ModbusTCPFrame, slave: Slave) -> bytes:
        """处理写单个线圈"""
        if len(frame.data) < 4:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_DATA_VALUE
            )
        
        address, coil_value = struct.unpack('>HH', frame.data[:4])
        if coil_value not in [0x0000, 0xFF00]:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_DATA_VALUE
            )
        
        value = (coil_value == 0xFF00)
        slave._set_values_by_type(defines.COILS, address, [value])
        
        return ModbusTCPFrame.build_write_single_coil_response(frame.transaction_id, frame.unit_id, address, value)
    
    def _handle_write_single_register(self, frame: ModbusTCPFrame, slave: Slave) -> bytes:
        """处理写单个寄存器"""
        if len(frame.data) < 4:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_DATA_VALUE
            )
        
        address, value = struct.unpack('>HH', frame.data[:4])
        slave._set_values_by_type(defines.HOLDING_REGISTERS, address, [value])
        
        # 回显响应
        data = struct.pack('>HH', address, value)
        return ModbusTCPFrame.build_request(frame.transaction_id, frame.unit_id, frame.function_code, data)
    
    def _handle_write_multiple_coils(self, frame: ModbusTCPFrame, slave: Slave) -> bytes:
        """处理写多个线圈"""
        if len(frame.data) < 5:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_DATA_VALUE
            )
        
        start_addr, quantity, byte_count = struct.unpack('>HHB', frame.data[:5])
        coil_bytes = frame.data[5:5+byte_count]
        
        # 解析线圈值
        values = []
        for byte in coil_bytes:
            for bit in range(8):
                if len(values) < quantity:
                    values.append(bool((byte >> bit) & 1))
        
        slave._set_values_by_type(defines.COILS, start_addr, values)
        
        # 响应
        data = struct.pack('>HH', start_addr, quantity)
        return ModbusTCPFrame.build_request(frame.transaction_id, frame.unit_id, frame.function_code, data)
    
    def _handle_write_multiple_registers(self, frame: ModbusTCPFrame, slave: Slave) -> bytes:
        """处理写多个寄存器"""
        if len(frame.data) < 5:
            return ModbusTCPFrame.build_error_response(
                frame.transaction_id, frame.unit_id, frame.function_code, defines.ILLEGAL_DATA_VALUE
            )
        
        start_addr, quantity, byte_count = struct.unpack('>HHB', frame.data[:5])
        register_data = frame.data[5:5+byte_count]
        
        # 解析寄存器值
        values = []
        for i in range(0, byte_count, 2):
            value = struct.unpack('>H', register_data[i:i+2])[0]
            values.append(value)
        
        slave._set_values_by_type(defines.HOLDING_REGISTERS, start_addr, values)
        
        # 响应
        data = struct.pack('>HH', start_addr, quantity)
        return ModbusTCPFrame.build_request(frame.transaction_id, frame.unit_id, frame.function_code, data)
