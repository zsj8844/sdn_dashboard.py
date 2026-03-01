"""
OpenFlow 扩展字段演示程序
"""

from .manager import create_iot_extension, IoTExtensionManager

def demo_extension_usage():
    """演示扩展字段的基本使用"""
    print("=== OpenFlow 扩展字段演示 ===\n")
    
    try:
        # 创建并测试扩展字段
        ext_mgr = create_iot_extension(
            sensor_type='temp',
            device_priority=3,
            route_select='route_a'
        )
        
        # 显示基本信息
        print("字段信息:")
        ext_mgr.print_fields()
        
        # 测试序列化/反序列化
        serialized = ext_mgr.serialize_to_experimenter()
        parsed_mgr = IoTExtensionManager.parse_from_experimenter(serialized)
        
        print(f"\n序列化测试: {len(serialized)} bytes")
        print("反序列化成功")
        
        print("\n✓ 测试完成!")
        return True
        
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False

if __name__ == '__main__':
    demo_extension_usage()