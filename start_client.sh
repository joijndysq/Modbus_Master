#!/bin/bash
echo "=========================================="
echo "           Modbus 上位机启动脚本"
echo "=========================================="
echo "2.配置连接参数"
echo "请选择连接方式:"
echo " 1)Modbus TCP (TCP)"
echo " 2)Modbus RTU (串口)"
read -p "选择 [1/2]: " choice

case $choice in
    1)
        read -p "输入从站IP地址(如192.168.3.104): " MODBUS_IP
        export MODBUS_HOST=$MODBUS_IP
        # export MODBUS_SERIAL=""
        export ZMQ_ENDPOINT="tcp://*:5555"
        echo "已配置 Modbus TCP: $MODBUS_HOST"
        ;;
    2)
        read -p "输入使用的串口路径(/dev/ttyUSB0): " SERIAL_PORT
        if [ -z "$SERIAL_PORT" ]; then
            SERIAL_PORT="/dev/ttyUSB0"
        fi
        # export MODBUS_HOST=""
        export MODBUS_SERIAL=$SERIAL_PORT
        export ZMQ_ENDPOINT="tcp://*:5555"
        echo "已配置 Modbus RTU: $MODBUS_SERIAL"
        ;;
    *)
        echo "无效选择，退出"
        exit 1
        ;;
esac
echo

export QT_QPA_PLATFORM_PLUGIN_PATH=''
echo "3. 启动上位机界面..."
echo "环境变量:"
echo "  MODBUS_HOST=$MODBUS_HOST"
echo "  MODBUS_SERIAL=$MODBUS_SERIAL"
echo "  ZMQ_ENDPOINT=$ZMQ_ENDPOINT"
echo
echo "正在启动..."
/home/lyric/anaconda3/envs/cv/bin/python window.py
