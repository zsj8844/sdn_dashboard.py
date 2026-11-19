
from ryu.lib.packet import lldp

print("=== lldp module contents ===")
print(dir(lldp))

print("\n=== lldp.lldp class contents ===")
if hasattr(lldp, 'lldp'):
    print(dir(lldp.lldp))

print("\n=== TLV classes ===")
tlv_classes = [cls for cls in dir(lldp) if not cls.startswith('_')]
for cls_name in tlv_classes:
    cls = getattr(lldp, cls_name)
    if hasattr(cls, 'tlv_type') or hasattr(cls, '__name__'):
        print(f"{cls_name}: {dir(cls)}")

print("\n=== Checking TLV types ===")
test_tlvs = [
    lldp.ChassisID,
    lldp.PortID,
    lldp.TTL,
    lldp.SystemName,
    lldp.End
]
for tlv_cls in test_tlvs:
    print(f"{tlv_cls.__name__}:")
    print(f"  tlv_type attribute: {hasattr(tlv_cls, 'tlv_type')}")
    if hasattr(tlv_cls, 'tlv_type'):
        print(f"  Value: {tlv_cls.tlv_type}")
    print(f"  Type of tlv_cls: {type(tlv_cls)}")
