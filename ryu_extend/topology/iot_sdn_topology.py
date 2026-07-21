from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel
import subprocess
import time
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
VENV_NAME = os.environ.get('VENV_NAME', 'ryu-env')

def get_python_path():
    venv_path = os.path.join(os.path.dirname(PROJECT_ROOT), '.venv', 'bin', 'python3')
    if os.path.exists(venv_path):
        return venv_path
    if 'CONDA_PREFIX' in os.environ:
        return os.path.join(os.environ['CONDA_PREFIX'], 'envs', VENV_NAME, 'bin', 'python3')
    return sys.executable

def setup_host_networking(host):
    host.cmd('ip link set lo up')
    host.cmd('iptables -F')
    host.cmd('iptables -t nat -F')
    host.cmd('iptables -P INPUT ACCEPT')
    host.cmd('iptables -P FORWARD ACCEPT')
    host.cmd('iptables -P OUTPUT ACCEPT')
    host.cmd('ip addr flush all')
    host.cmd('ip route flush table main')

    if host.name == 'iot3':
        print("  iot3 接口列表:", [intf.name for intf in host.intfs.values() if intf.name != 'lo'])

        interface_configs = [
            ('iot3-eth0', '192.168.2.1/24'),
            ('iot3-eth1', '192.168.3.1/24'),
            ('iot3-eth2', '192.168.4.1/24'),
            ('iot3-eth3', '192.168.1.12/24')
        ]

        intf_list = [intf for intf in host.intfs.values() if intf.name != 'lo']
        for i, intf in enumerate(intf_list):
            if i < len(interface_configs):
                intf_name, ip_addr = interface_configs[i]
                host.cmd('ip link set {} up'.format(intf.name))
                host.cmd('ip addr add {} dev {}'.format(ip_addr, intf.name))

        host.cmd('sysctl -w net.ipv4.ip_forward=1 > /dev/null 2>&1')
        print("  iot3 IP转发已开启（纯路由模式，路由由SDN控制器流表决策）")
        print("  iot3 接口配置:")
        print("    - iot3-eth0: 192.168.2.1 (连接iot1)")
        print("    - iot3-eth1: 192.168.3.1 (连接iot2)")
        print("    - iot3-eth2: 192.168.4.1 (连接iot4)")
        print("    - iot3-eth3: 192.168.1.12 (连接s1)")
    elif host.name == 'iot1':
        intf_list = [intf for intf in host.intfs.values() if intf.name != 'lo']
        if intf_list:
            host.cmd('ip link set {} up'.format(intf_list[0].name))
            host.cmd('ip addr add 192.168.2.10/24 dev {}'.format(intf_list[0].name))
            host.cmd('ip route add default via 192.168.2.1 dev {}'.format(intf_list[0].name))
    elif host.name == 'iot2':
        intf_list = [intf for intf in host.intfs.values() if intf.name != 'lo']
        if intf_list:
            host.cmd('ip link set {} up'.format(intf_list[0].name))
            host.cmd('ip addr add 192.168.3.11/24 dev {}'.format(intf_list[0].name))
            host.cmd('ip route add default via 192.168.3.1 dev {}'.format(intf_list[0].name))
    elif host.name == 'iot4':
        intf_list = [intf for intf in host.intfs.values() if intf.name != 'lo']
        if intf_list:
            host.cmd('ip link set {} up'.format(intf_list[0].name))
            host.cmd('ip addr add 192.168.4.13/24 dev {}'.format(intf_list[0].name))
            host.cmd('ip route add default via 192.168.4.1 dev {}'.format(intf_list[0].name))
    elif host.name == 'h1':
        intf_list = [intf for intf in host.intfs.values() if intf.name != 'lo']
        if intf_list:
            host.cmd('ip link set {} up'.format(intf_list[0].name))
            host.cmd('ip addr add 192.168.1.20/24 dev {}'.format(intf_list[0].name))
            host.cmd('ip route add default via 192.168.1.12 dev {}'.format(intf_list[0].name))
    elif host.name == 'h2':
        intf_list = [intf for intf in host.intfs.values() if intf.name != 'lo']
        if intf_list:
            host.cmd('ip link set {} up'.format(intf_list[0].name))
            host.cmd('ip addr add 192.168.1.21/24 dev {}'.format(intf_list[0].name))
            host.cmd('ip route add default via 192.168.1.12 dev {}'.format(intf_list[0].name))

def create_iot_sdn_topology():
    subprocess.run(["sudo", "mn", "-c"], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "ovs-vsctl", "del-br", "s1"], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "ovs-vsctl", "del-br", "s2"], check=False, stdout=subprocess.DEVNULL)

    net = Mininet(
        controller=RemoteController,
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=True
    )

    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6634, protocols='OpenFlow13')
    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    s2 = net.addSwitch('s2', protocols='OpenFlow13')
    iot1 = net.addHost('iot1')
    iot2 = net.addHost('iot2')
    iot3 = net.addHost('iot3')
    iot4 = net.addHost('iot4')
    h1 = net.addHost('h1')
    h2 = net.addHost('h2')

    net.addLink(iot1, iot3)
    net.addLink(iot2, iot3)
    net.addLink(iot4, iot3)
    net.addLink(iot3, s1)
    net.addLink(s1, s2)
    net.addLink(s2, h1)
    net.addLink(s2, h2)

    net.start()
    s1.cmd('ifconfig s1 192.168.1.1/24 up')
    s2.cmd('ifconfig s2 192.168.1.2/24 up')

    print(" 配置主机网络参数...")
    for host in [iot1, iot2, iot3, iot4, h1, h2]:
        setup_host_networking(host)

    python_path = get_python_path()
    gateway_script = os.path.join(PROJECT_ROOT, 'topology', 'iot_gateway_enhanced.py')
    gateway_log = os.path.join(PROJECT_ROOT, 'logs', 'gateway.log')

    print(" 在 iot3 (网关) 上自动启动 IoT 网关程序...")
    iot3.cmd('nohup {} {} > {} 2>&1 &'.format(python_path, gateway_script, gateway_log))

    time.sleep(5)

    print("\n=== 网络连通性测试 ===")

    print("\n  IoT设备与网关的连通性:")
    iot_gateway_ips = {
        'iot1': '192.168.2.1',
        'iot2': '192.168.3.1',
        'iot4': '192.168.4.1'
    }

    for host in [iot1, iot2, iot4]:
        gateway_ip = iot_gateway_ips[host.name]
        ping_result = host.cmd('ping -c 3 {} -W 2'.format(gateway_ip))
        if '3 received' in ping_result:
            print("  {} -> iot3连通".format(host.name))
        else:
            print("  {} -> iot3不通".format(host.name))

    print("\n  通过网关到外部网络的连通性:")
    test_hosts = [h1, h2]
    test_ips = ['192.168.1.20', '192.168.1.21']

    for iot_host in [iot1, iot2, iot4]:
        for j, test_host in enumerate(test_hosts):
            ping_result = iot_host.cmd('ping -c 3 {} -W 2'.format(test_ips[j]))
            if '3 received' in ping_result:
                print("  {} -> {} ({})连通".format(iot_host.name, test_host.name, test_ips[j]))
            else:
                print("  {} -> {} ({})不通".format(iot_host.name, test_host.name, test_ips[j]))

    print("\n=== SDN物联网拓扑完全就绪 ===")
    print("  控制器地址：127.0.0.1:6634 (OpenFlow13)")
    print("  IoT网关：iot3 (192.168.1.12)")
    print("  监控主机：h1 (192.168.1.20), h2 (192.168.1.21)")
    print("  网络连接：iot1/iot2/iot4 -> iot3 -> s1 -> s2 -> h1/h2")
    print("  调试命令：")
    print("   - 查看交换机流表：ovs-ofctl dump-flows s1 -O OpenFlow13")
    print("   - 查看控制器连接：ovs-vsctl show | grep Controller")
    print("   - 在h1启动监听：xterm h1 nc -ul 5005")
    print("=" * 60 + "\n")

    try:
        CLI(net)
    except KeyboardInterrupt:
        print("\n 收到中断信号，正在优雅关闭拓扑...")
    finally:
        net.stop()
        print(" SDN拓扑已关闭，所有资源清理完成")

if __name__ == '__main__':
    setLogLevel('warning')
    create_iot_sdn_topology()
