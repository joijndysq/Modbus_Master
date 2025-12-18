"""
ModBus 帧结构定义和解析模块
"""
import struct
from typing import Tuple, Optional


class ModbusTCPFrame:
    """ModBus TCP 帧处理类"""
    
    # MBAP Header 长度
    MBAP_HEADER_LENGTH = 7
    
    def __init__(self):
        self.transaction_id = 0
        self.protocol_id = 0  # ModBus协议固定为0
        self.length = 0
        self.unit_id = 1  # 单元标识符
        self.function_code = 0
        self.data = b''
    
    @staticmethod
    def build_request(transaction_id: int, unit_id: int, 
                     function_code: int, data: bytes) -> bytes:
        """
        构建ModBus TCP请求帧
        
        Args:
            transaction_id: 事务标识符
            unit_id: 单元标识符
            function_code: 功能码
            data: 数据部分
            
        Returns:
            完整的ModBus TCP帧
        """
        # PDU = function_code(1) + data
        pdu = struct.pack('B', function_code) + data
        
        # 长度 = unit_id(1) + PDU长度
        length = 1 + len(pdu)
        
        # MBAP Header
        mbap_header = struct.pack('>HHHB',
                                 transaction_id,  # 事务标识符
                                 0,              # 协议标识符
                                 length,         # 长度
                                 unit_id)        # 单元标识符
        
        return mbap_header + pdu
    
    @staticmethod
    def parse_frame(frame: bytes) -> Optional['ModbusTCPFrame']:
        """
        解析ModBus TCP帧
        
        Args:
            frame: 接收到的完整帧
            
        Returns:
            解析后的ModbusTCPFrame对象，解析失败返回None
        """
        if len(frame) < ModbusTCPFrame.MBAP_HEADER_LENGTH + 1:
            return None
        
        try:
            # 解析MBAP头
            transaction_id, protocol_id, length, unit_id = struct.unpack(
                '>HHHB', frame[:ModbusTCPFrame.MBAP_HEADER_LENGTH]
            )
            
            # 检查协议标识符
            if protocol_id != 0:
                return None
            
            # 解析PDU
            function_code = frame[ModbusTCPFrame.MBAP_HEADER_LENGTH]
            data = frame[ModbusTCPFrame.MBAP_HEADER_LENGTH + 1:]
            
            # 创建帧对象
            mb_frame = ModbusTCPFrame()
            mb_frame.transaction_id = transaction_id
            mb_frame.protocol_id = protocol_id
            mb_frame.length = length
            mb_frame.unit_id = unit_id
            mb_frame.function_code = function_code
            mb_frame.data = data
            
            return mb_frame
            
        except struct.error:
            return None
    
    @staticmethod
    def build_read_coils_request(transaction_id: int, unit_id: int,
                                start_address: int, quantity: int) -> bytes:
        """
        构建读线圈请求 (功能码 0x01)
        
        Args:
            transaction_id: 事务ID
            unit_id: 单元ID
            start_address: 起始地址
            quantity: 数量
        """
        data = struct.pack('>HH', start_address, quantity)
        return ModbusTCPFrame.build_request(transaction_id, unit_id, 0x01, data)
    
    @staticmethod
    def build_read_holding_registers_request(transaction_id: int, unit_id: int,
                                            start_address: int, quantity: int) -> bytes:
        """
        构建读保持寄存器请求 (功能码 0x03)
        """
        data = struct.pack('>HH', start_address, quantity)
        return ModbusTCPFrame.build_request(transaction_id, unit_id, 0x03, data)
    
    @staticmethod
    def build_write_single_coil_request(transaction_id: int, unit_id: int,
                                       address: int, value: bool) -> bytes:
        """
        构建写单个线圈请求 (功能码 0x05)
        
        Args:
            transaction_id: 事务ID
            unit_id: 单元ID
            address: 线圈地址
            value: True为ON(0xFF00), False为OFF(0x0000)
        """
        coil_value = 0xFF00 if value else 0x0000
        data = struct.pack('>HH', address, coil_value)
        return ModbusTCPFrame.build_request(transaction_id, unit_id, 0x05, data)
    
    @staticmethod
    def parse_read_coils_response(frame: 'ModbusTCPFrame') -> Optional[list]:
        """
        解析读线圈响应
        
        Returns:
            线圈状态列表 [True/False, ...]
        """
        if frame.function_code != 0x01:
            return None
        
        if len(frame.data) < 1:
            return None
        
        byte_count = frame.data[0]
        coil_bytes = frame.data[1:1+byte_count]
        
        coils = []
        for byte in coil_bytes:
            for bit in range(8):
                coils.append(bool((byte >> bit) & 1))
        
        return coils
    
    @staticmethod
    def parse_read_holding_registers_response(frame: 'ModbusTCPFrame') -> Optional[list]:
        """
        解析读保持寄存器响应
        
        Returns:
            寄存器值列表 [value1, value2, ...]
        """
        if frame.function_code != 0x03:
            return None
        
        if len(frame.data) < 1:
            return None
        
        byte_count = frame.data[0]
        register_data = frame.data[1:1+byte_count]
        
        registers = []
        for i in range(0, byte_count, 2):
            value = struct.unpack('>H', register_data[i:i+2])[0]
            registers.append(value)
        
        return registers
    
    @staticmethod
    def build_read_coils_response(transaction_id: int, unit_id: int,
                                 coil_status: list) -> bytes:
        """
        构建读线圈响应
        
        Args:
            coil_status: 线圈状态列表 [True/False, ...]
        """
        # 计算需要的字节数
        byte_count = (len(coil_status) + 7) // 8
        
        # 打包线圈状态
        coil_bytes = bytearray(byte_count)
        for i, status in enumerate(coil_status):
            if status:
                byte_index = i // 8
                bit_index = i % 8
                coil_bytes[byte_index] |= (1 << bit_index)
        
        data = struct.pack('B', byte_count) + bytes(coil_bytes)
        return ModbusTCPFrame.build_request(transaction_id, unit_id, 0x01, data)
    
    @staticmethod
    def build_read_holding_registers_response(transaction_id: int, unit_id: int,
                                             register_values: list) -> bytes:
        """
        构建读保持寄存器响应
        """
        byte_count = len(register_values) * 2
        data = struct.pack('B', byte_count)
        
        for value in register_values:
            data += struct.pack('>H', value)
        
        return ModbusTCPFrame.build_request(transaction_id, unit_id, 0x03, data)
    
    @staticmethod
    def build_write_single_coil_response(transaction_id: int, unit_id: int,
                                        address: int, value: bool) -> bytes:
        """
        构建写单个线圈响应（回显请求）
        """
        coil_value = 0xFF00 if value else 0x0000
        data = struct.pack('>HH', address, coil_value)
        return ModbusTCPFrame.build_request(transaction_id, unit_id, 0x05, data)
    
    @staticmethod
    def build_error_response(transaction_id: int, unit_id: int,
                           function_code: int, exception_code: int) -> bytes:
        """
        构建异常响应
        
        Args:
            exception_code: 异常码 (1=非法功能, 2=非法地址, 3=非法数据值, 4=从站设备故障)
        """
        error_function_code = function_code | 0x80
        data = struct.pack('B', exception_code)
        return ModbusTCPFrame.build_request(transaction_id, unit_id, 
                                          error_function_code, data)


class ModbusCRC:
    """ModBus CRC校验（为RTU模式预留）"""
    
    @staticmethod
    def calculate_crc(data: bytes) -> int:
        """计算ModBus CRC16"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc
    
    @staticmethod
    def verify_crc(data: bytes, crc: int) -> bool:
        """验证CRC"""
        calculated_crc = ModbusCRC.calculate_crc(data)
        return calculated_crc == crc
