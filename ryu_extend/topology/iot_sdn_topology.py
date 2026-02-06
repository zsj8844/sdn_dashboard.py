from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch, Host
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel
import argparse
import logging

def create_iot_sdn_topology():
    # 清理残留
    from subprocess import run
    run(["sudo", "mn", "-c"], check=False)
    run(["sudo", "ovs-vsctl", "del-br", "s1"], check=False)
    run(["sudo", "ovs-vsctl", "del-br", "s2"], check=False)

    # 初始化网络
    net = Mininet(
        controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6634),
        switch=lambda name, **kwargs: OVSKernelSwitch(name, protocols='OpenFlow13', **kwargs),
        autoSetMacs=True
    )

    # 添加设备
    c0 = net.addController('c0')
    s1 = net.addSwitch('s1')
    s2 = net.addSwitch('s2')

    iot1 = net.addHost('iot1', ip='192.168.1.10')
    iot2 = net.addHost('iot2', ip='192.168.1.11')
    iot3 = net.addHost('iot3', ip='192.168.1.12')
    iot4 = net.addHost('iot4', ip='192.168.1.13')  # 分配新IP，避免冲突
    
    h1 = net.addHost('h1', ip='192.168.1.20')
    h2 = net.addHost('h2', ip='192.168.1.21')

    # 添加链路
    net.addLink(iot1, s1)
    net.addLink(iot2, s1)
    net.addLink(iot3, s1)
    net.addLink(s1, s2)
    net.addLink(s2, h1)
    net.addLink(s2, h2)
    net.addLink(iot4, s1)  # 将iot4连接到交换机s1
    
    # 启动网络
    net.start()
    CLI(net)
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    create_iot_sdn_topology()

