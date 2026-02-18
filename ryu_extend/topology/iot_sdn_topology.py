from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch, Host
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel
import argparse
import logging
import subprocess
import time

def setup_host_networking(host):
    """配置主机网络参数 - 最终稳定版"""
    host.cmd('ip link set lo up')
    # 清空防火墙规则，确保所有流量通行
    host.cmd('iptables -F')
    host.cmd('iptables -P INPUT ACCEPT')
    host.cmd('iptables -P FORWARD ACCEPT')
    host.cmd('iptables -P OUTPUT ACCEPT')
    
    # 清空现有IP和路由，彻底避免冲突
    host.cmd('ip addr flush all')
    host.cmd('ip route flush table main')
    
    # 为所有主机配置网络接口（适配多接口场景）
    ip_map = {
        'iot1': '192.168.1.10/24',
        'iot2': '192.168.1.11/24', 
        'iot3': '192.168.1.12/24',
        'iot4': '192.168.1.13/24',
        'h1': '192.168.1.20/24',
        'h2': '192.168.1.21/24'
    }
    
    if host.name in ip_map:
        # 遍历所有接口，强制激活并清空IP
        for intf in host.intfs.values():
            host.cmd(f'ip link set {intf.name} up')
            host.cmd(f'ip addr flush dev {intf.name}')
            
            # 核心修复：iot3的所有物理接口都配相同IP
            if host.name == 'iot3' and intf.name != 'lo':
                host.cmd(f'ip addr add {ip_map[host.name]} dev {intf.name}')
            # 其他主机仅给第一个物理接口配IP
            elif intf.name != 'lo' and not host.cmd(f'ip addr show {intf.name} | grep "{ip_map[host.name]}"'):
                # 如果该接口还没有配置IP，则配置
                host.cmd(f'ip addr add {ip_map[host.name]} dev {intf.name}')
                break  # 只给第一个非lo接口配IP
        
        # 给所有主机添加默认路由（指向iot3网关）
        # 获取第一个物理接口名称
        physical_intfs = [intf.name for intf in host.intfs.values() if intf.name != 'lo']
        if physical_intfs:
            host.cmd(f'ip route add default via 192.168.1.12 dev {physical_intfs[0]}')
    
    # iot3网关启用IP转发（核心：让流量能转发到s1）
    if host.name == 'iot3':
        host.cmd('sysctl -w net.ipv4.ip_forward=1 > /dev/null 2>&1')

def start_iot_gateway_simulation(net):
    """启动IoT网关模拟（稳定版，带日志）"""
    print(" 启动IoT网关模拟器...")
    iot3 = net.get('iot3')
    setup_host_networking(iot3)
    import time
    time.sleep(3)
    
    # 启动模拟器（用shell=True避免路径问题，重定向日志便于调试）
    simulator_path = '/home/zhang/桌面/ryucontronl/ryu_extend/topology/iot_gateway_simulator.py'
    log_path = '/tmp/iot_gateway_simulator.log'
    cmd = f'python3 {simulator_path} > {log_path} 2>&1'
    iot3_process = iot3.popen(cmd, shell=True)
    
    print(f" iot3网关模拟器已启动 (PID: {iot3_process.pid})")
    print(f" 模拟器日志路径：{log_path} (可执行 tail -f {log_path} 查看实时日志)")
    return iot3_process

def create_iot_sdn_topology():
    # 强力清理残留（包括进程、网桥、流表）
    subprocess.run(["sudo", "mn", "-c"], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "ovs-vsctl", "del-br", "s1"], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "ovs-vsctl", "del-br", "s2"], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "pkill", "-f", "iot_gateway_simulator.py"], check=False, stdout=subprocess.DEVNULL)

    # 初始化网络
    net = Mininet(
        controller=RemoteController,
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=True
    )

    # 添加核心设备（关键：指定控制器IP+端口+OpenFlow13）
    c0 = net.addController(
        'c0',
        controller=RemoteController,
        ip='127.0.0.1',
        port=6634,  # 匹配你的RYU控制器端口
        protocols='OpenFlow13'
    )
    # 交换机必须指定OpenFlow13
    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    s2 = net.addSwitch('s2', protocols='OpenFlow13')

    # 添加主机（仅定义名称，IP在setup_host_networking中配置）
    iot1 = net.addHost('iot1')
    iot2 = net.addHost('iot2')
    iot3 = net.addHost('iot3')  # IoT网关
    iot4 = net.addHost('iot4')
    h1 = net.addHost('h1')      # 监控主机
    h2 = net.addHost('h2')

    # 拓扑连接
    net.addLink(iot1, iot3)
    net.addLink(iot2, iot3)
    net.addLink(iot4, iot3)
    net.addLink(iot3, s1)
    net.addLink(s1, s2)
    net.addLink(s2, h1)
    net.addLink(s2, h2)

    # 启动网络
    net.start()

    # 给交换机配置临时管理IP（仅用于调试，不影响数据平面）
    s1.cmd('ifconfig s1 192.168.1.1/24 up')
    s2.cmd('ifconfig s2 192.168.1.2/24 up')

    # 配置所有主机网络
    print("️  配置主机网络参数...")
    for host in [iot1, iot2, iot3, iot4, h1, h2]:
        setup_host_networking(host)

    # 启动网关模拟器
    gateway_process = start_iot_gateway_simulation(net)

    # 延长网络稳定时间（关键：从2秒→5秒）
    time.sleep(5)

    # 增强版连通性测试（自动获取真实MAC，无需手动配置）
    print("\n===  网络连通性测试 ===")
    # 1. 测试IoT设备 -> 网关（iot3）（延长超时到2秒）
    iot3_ip = '192.168.1.12'
    for host in [iot1, iot2, iot4]:
        # 强制刷新ARP
        iot3_mac = iot3.MAC()
        host.cmd(f'arp -d {iot3_ip} 2>/dev/null || true')  # 删除旧ARP
        host.cmd(f'arp -s {iot3_ip} {iot3_mac}')           # 重新配置
        
        # 测试ping（超时2秒，发送3个包，更准确）
        ping_result = host.cmd(f'ping -c 3 {iot3_ip} -W 2')
        if '3 received' in ping_result:
            print(f"  {host.name} -> iot3 (网关) 连通")
        else:
            print(f"  {host.name} -> iot3 (网关) 不通")
            # 强制修复接口
            for intf in host.intfs.values():
                host.cmd(f'ip link set {intf.name} up')
    
    # 2. 修复：测试iot3 -> h1（替代ping s1，验证数据能通过s1转发）
    h1_ip = '192.168.1.20'
    iot3.cmd(f'arp -s {h1_ip} {h1.MAC()}')
    h1_ping = iot3.cmd(f'ping -c 3 {h1_ip} -W 2')
    print(f"  iot3 -> h1 (通过s1/s2) 连通" if '3 received' in h1_ping else f"  iot3 -> h1 (通过s1/s2) 不通")

    print("\n===  SDN物联网拓扑完全就绪 ===")
    print(f"  控制器地址：127.0.0.1:6634 (OpenFlow13)")
    print(f"  IoT网关：iot3 ({iot3_ip})")
    print(f"️  监控主机：h1 (192.168.1.20), h2 (192.168.1.21)")
    print(f"  调试命令：")
    print(f"   - 查看网关日志：tail -f /tmp/iot_gateway_simulator.log")
    print(f"   - 查看交换机流表：ovs-ofctl dump-flows s1 -O OpenFlow13")
    print(f"   - 查看控制器连接：ovs-vsctl show | grep Controller")
    print(f"   - 在h1启动监听：xterm h1  nc -ul 5005")
    print("=" * 60 + "\n")
    
    try:
        CLI(net)  # 启动Mininet交互终端
    except KeyboardInterrupt:
        print("\n️  收到中断信号，正在优雅关闭拓扑...")
    finally:
        # 停止网关模拟器（安全判断）
        if 'gateway_process' in locals():
            try:
                gateway_process.terminate()
                gateway_process.wait(timeout=5)
                print(" 网关模拟器已停止")
            except Exception as e:
                print(f"️  停止网关模拟器失败：{str(e)}")
        # 停止网络+最终清理
        net.stop()
        subprocess.run(["sudo", "pkill", "-f", "iot_gateway_simulator.py"], check=False)
        print(" SDN拓扑已关闭，所有资源清理完成")

if __name__ == '__main__':
    setLogLevel('warning')  # 降低日志级别，只看关键信息
    create_iot_sdn_topology()

