#!/usr/bin/env python3
"""
OpenFlow 数据包分析工具
用于分析包含扩展字段的OpenFlow数据包
"""

import struct
import sys

def analyze_experimenter_data(data):
    """分析Experimenter字段数据"""
    print("=== OpenFlow Experimenter 数据包分析 ===\n")
    
    if len(data) < 5:
        print("错误: 数据包长度不足")
        return False
    
    # 解析头部
    try:
        exp_id, field_count = struct.unpack('!IB', data[:5])
        print(f"厂商ID: 0x{exp_id:08x}")
        print(f"字段数量: {field_count}")
        
        if field_count == 0:
            print("无扩展字段")
            return True
            
        buf = data[5:]
        print(f"\n字段详情:")
        print("-" * 40)
        
        field_types = {
            1: "SensorType(传感器类型)",
            2: "DevicePriority(设备优先级)", 
            3: "RouteSelect(路由选择)"
        }
        
        sensor_names = {
            1: "温度传感器",
            2: "湿度传感器", 
            3: "光照传感器",
            4: "移动传感器",
            5: "压力传感器",
            6: "气体传感器",
            7: "声音传感器"
        }
        
        priority_names = {
            1: "低优先级",
            2: "普通优先级",
            3: "高优先级", 
            4: "关键优先级",
            5: "紧急优先级"
        }
        
        route_names = {
            1: "路径A(主路径)",
            2: "路径B(备用路径)"
        }
        
        for i in range(field_count):
            if len(buf) < 6:
                print(f"字段 {i+1}: 数据不完整")
                break
                
            field_type, reserved, value = struct.unpack('!BBI', buf[:6])
            buf = buf[6:]
            
            print(f"字段 {i+1}:")
            print(f"  类型: {field_type} ({field_types.get(field_type, '未知类型')})")
            print(f"  值: {value}")
            
            # 根据字段类型解释值
            if field_type == 1:  # SensorType
                sensor_name = sensor_names.get(value, f"未知传感器({value})")
                print(f"  含义: {sensor_name}")
            elif field_type == 2:  # DevicePriority
                priority_name = priority_names.get(value, f"级别{value}")
                print(f"  含义: {priority_name}")
            elif field_type == 3:  # RouteSelect
                route_name = route_names.get(value, f"路径{value}")
                print(f"  含义: {route_name}")
            else:
                print(f"  含义: 未知字段类型")
            
            print()
            
        return True
        
    except Exception as e:
        print(f"解析错误: {e}")
        return False

def hex_dump(data, width=16):
    """十六进制转储"""
    print("十六进制数据:")
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print(f"{i:04x}: {hex_part:<48} {ascii_part}")

def main():
    """主函数"""
    print("OpenFlow 扩展字段分析工具\n")
    
    # 示例数据分析
    if len(sys.argv) > 1:
        # 从文件读取数据
        try:
            with open(sys.argv[1], 'rb') as f:
                data = f.read()
            print(f"分析文件: {sys.argv[1]}")
        except Exception as e:
            print(f"读取文件失败: {e}")
            return
    else:
        # 使用示例数据
        print("使用示例数据进行演示...")
        # 构造示例数据包: 厂商ID + 字段数 + 3个字段
        sample_data = (
            b'\x12\x34\x56\x78' +  # 厂商ID
            b'\x03' +              # 3个字段
            b'\x01\x00\x00\x00\x00\x01' +  # SensorType=1(temp)
            b'\x02\x00\x00\x00\x00\x03' +  # DevicePriority=3(high)
            b'\x03\x00\x00\x00\x00\x01'    # RouteSelect=1(route_a)
        )
        data = sample_data
    
    print(f"数据包总长度: {len(data)} 字节\n")
    
    # 十六进制转储
    hex_dump(data)
    print()
    
    # 分析Experimenter字段
    success = analyze_experimenter_data(data)
    
    if success:
        print("✓ 分析完成")
    else:
        print("✗ 分析失败")

if __name__ == '__main__':
    main()