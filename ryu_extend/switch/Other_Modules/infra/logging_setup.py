"""控制器日志配置"""

import os
import logging


def setup_logging(base_dir=None):
    """配置 ryu 和控制器日志输出到文件 + 控制台"""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    log_dir = os.path.join(base_dir, '../../logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'controller.log')

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Ryu 日志
    ryu_logger = logging.getLogger('ryu')
    ryu_logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    ryu_logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    ryu_logger.addHandler(console_handler)

    # 控制器应用日志
    ble_logger = logging.getLogger('ryu.app.simple_switch_13')
    ble_logger.setLevel(logging.DEBUG)
    ble_logger.addHandler(file_handler)
    ble_logger.addHandler(console_handler)

    return log_file
