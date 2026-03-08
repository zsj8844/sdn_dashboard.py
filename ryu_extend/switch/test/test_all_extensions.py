#!/usr/bin/env python3
"""测试所有扩展字段"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
sys.path.insert(0, current_dir)

print("="*60)
print("测试所有扩展字段")
print("="*60)

try:
    from extensions.manager import IoTExtensionManager, create_iot_extension
    from extensions.sensor_field import SensorTypeField
    from extensions.priority_field import DevicePriorityField
    from extensions.route_field import RouteSelectField
    from extensions.app_field import AppDeploymentField
    from extensions.role_field import RoleSwitchField
    
    print("✓ 所有扩展模块导入成功")
    print()
    
    # 测试1: 传感器类型字段
    print("1. 测试传感器类型字段...")
    sensor_field = SensorTypeField('temp')
    print(f"   - 创建: {sensor_field}")
    serialized = sensor_field.serialize()
    print(f"   - 序列化: {len(serialized)} bytes")
    parsed = SensorTypeField.parse(serialized)
    print(f"   - 解析: {parsed}")
    print("   ✓ 传感器类型字段测试通过")
    print()
    
    # 测试2: 设备优先级字段
    print("2. 测试设备优先级字段...")
    priority_field = DevicePriorityField(3)
    print(f"   - 创建: {priority_field}")
    serialized = priority_field.serialize()
    print(f"   - 序列化: {len(serialized)} bytes")
    parsed = DevicePriorityField.parse(serialized)
    print(f"   - 解析: {parsed}")
    print("   ✓ 设备优先级字段测试通过")
    print()
    
    # 测试3: 路由选择字段
    print("3. 测试路由选择字段...")
    route_field = RouteSelectField('route_a')
    print(f"   - 创建: {route_field}")
    serialized = route_field.serialize()
    print(f"   - 序列化: {len(serialized)} bytes")
    parsed = RouteSelectField.parse(serialized)
    print(f"   - 解析: {parsed}")
    print("   ✓ 路由选择字段测试通过")
    print()
    
    # 测试4: 应用下发字段
    print("4. 测试应用下发字段...")
    app_field = AppDeploymentField('test_app', 1, '1.0.0')
    print(f"   - 创建: {app_field}")
    serialized = app_field.serialize()
    print(f"   - 序列化: {len(serialized)} bytes")
    parsed = AppDeploymentField.parse(serialized)
    print(f"   - 解析: {parsed}")
    print("   ✓ 应用下发字段测试通过")
    print()
    
    # 测试5: 角色切换字段
    print("5. 测试角色切换字段...")
    role_field = RoleSwitchField(2, True)
    print(f"   - 创建: {role_field}")
    serialized = role_field.serialize()
    print(f"   - 序列化: {len(serialized)} bytes")
    parsed = RoleSwitchField.parse(serialized)
    print(f"   - 解析: {parsed}")
    print("   ✓ 角色切换字段测试通过")
    print()
    
    # 测试6: 完整的IoT扩展管理器
    print("6. 测试完整的IoT扩展管理器...")
    manager = IoTExtensionManager()
    manager.add_field(SensorTypeField('humidity'))
    manager.add_field(DevicePriorityField(4))
    manager.add_field(RouteSelectField('route_b'))
    manager.add_field(AppDeploymentField('app1', 2, '2.0.0'))
    manager.add_field(RoleSwitchField(3, False))
    
    print("   - 字段数量:", len(manager.fields))
    serialized_data = manager.serialize_to_experimenter()
    print(f"   - 完整序列化: {len(serialized_data)} bytes")
    
    parsed_manager = IoTExtensionManager.parse_from_experimenter(serialized_data)
    print("   - 解析后字段数量:", len(parsed_manager.fields))
    field_dict = parsed_manager.get_field_dict()
    print(f"   - 字段字典: {field_dict}")
    print("   ✓ 完整IoT扩展管理器测试通过")
    print()
    
    # 测试7: create_iot_extension便捷函数
    print("7. 测试create_iot_extension便捷函数...")
    ext = create_iot_extension(
        sensor_type='light',
        device_priority=5,
        route_select='route_b',
        app_deployment={'app_id': 'my_app', 'action': 1, 'version': '1.0.0'},
        role_switch={'target_mode': 2, 'force': True}
    )
    print(f"   - 创建成功")
    field_dict = ext.get_field_dict()
    print(f"   - 字段字典: {field_dict}")
    print("   ✓ create_iot_extension测试通过")
    print()
    
    print("="*60)
    print("✓ 所有测试通过！")
    print("="*60)
    
except Exception as e:
    print(f"\n✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
