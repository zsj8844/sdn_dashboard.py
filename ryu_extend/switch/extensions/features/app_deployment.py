"""
应用下发功能模块
负责边缘应用的封装、下发和加载
"""

import hashlib
import json
import struct
from datetime import datetime
from enum import Enum

# DATA_FILTER - 数据过滤应用（值为1）
# AI_INFERENCE - AI推理应用（值为2）
# DATA_AGGREGATION - 数据聚合应用（值为3）
# CUSTOM - 自定义应用（值为4）
class AppType(Enum):
    DATA_FILTER = 1
    AI_INFERENCE = 2
    DATA_AGGREGATION = 3
    CUSTOM = 4


class AppStatus(Enum):
    NOT_DEPLOYED = 0
    DEPLOYING = 1
    RUNNING = 2
    STOPPED = 3
    ERROR = 4


class EdgeApplication:
    def __init__(self, app_id, app_name, app_type, app_code, version="1.0.0", description="", requirements=None):
        self.app_id = app_id
        self.app_name = app_name
        self.app_type = app_type
        self.app_code = app_code
        self.version = version
        self.description = description
        self.requirements = requirements or {}
        self.created_at = datetime.now().isoformat()
        self.checksum = hashlib.sha256(self.app_code.encode()).hexdigest()
        self.status = AppStatus.NOT_DEPLOYED
        self.deployed_devices = []
    
    def to_dict(self):
        return {
            'app_id': self.app_id,
            'app_name': self.app_name,
            'app_type': self.app_type.value,
            'app_code': self.app_code,
            'version': self.version,
            'description': self.description,
            'requirements': self.requirements,
            'created_at': self.created_at,
            'checksum': self.checksum,
            'status': self.status.value,
            'deployed_devices': self.deployed_devices
        }
    
    @classmethod
    def from_dict(cls, data):
        app = cls(
            app_id=data['app_id'],
            app_name=data['app_name'],
            app_type=AppType(data['app_type']),
            app_code=data['app_code'],
            version=data.get('version', '1.0.0'),
            description=data.get('description', ''),
            requirements=data.get('requirements', {})
        )
        app.status = AppStatus(data.get('status', AppStatus.NOT_DEPLOYED.value))
        app.deployed_devices = data.get('deployed_devices', [])
        return app


class AppDeploymentManager:
    def __init__(self):
        self.applications = {}
        self.deployment_history = []
    
    def create_application(self, app_id, app_name, app_type, app_code, version="1.0.0", description="", requirements=None):
        if app_id in self.applications:
            raise ValueError(f"应用ID {app_id} 已存在")
        app = EdgeApplication(app_id, app_name, app_type, app_code, version, description, requirements)
        self.applications[app_id] = app
        return app
    
    def deploy_application(self, app_id, device_id):
        if app_id not in self.applications:
            raise ValueError(f"应用 {app_id} 不存在")
        app = self.applications[app_id]
        deployment_record = {
            'app_id': app_id,
            'device_id': device_id,
            'timestamp': datetime.now().isoformat(),
            'action': 'deploy',
            'status': 'success'
        }
        app.status = AppStatus.RUNNING
        if device_id not in app.deployed_devices:
            app.deployed_devices.append(device_id)
        self.deployment_history.append(deployment_record)
        return deployment_record
    
    def undeploy_application(self, app_id, device_id):
        if app_id not in self.applications:
            raise ValueError(f"应用 {app_id} 不存在")
        app = self.applications[app_id]
        deployment_record = {
            'app_id': app_id,
            'device_id': device_id,
            'timestamp': datetime.now().isoformat(),
            'action': 'undeploy',
            'status': 'success'
        }
        if device_id in app.deployed_devices:
            app.deployed_devices.remove(device_id)
        if not app.deployed_devices:
            app.status = AppStatus.STOPPED
        self.deployment_history.append(deployment_record)
        return deployment_record
    
    def get_application(self, app_id):
        return self.applications.get(app_id)
    
    def list_applications(self):
        return list(self.applications.values())
    
    def get_deployment_history(self, app_id=None):
        if app_id:
            return [h for h in self.deployment_history if h['app_id'] == app_id]
        return self.deployment_history
