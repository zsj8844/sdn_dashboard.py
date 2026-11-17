import socket, struct, sys

path = sys.argv[1]
fm = open(sys.argv[2], 'rb').read()

def recv_msg(s):
    hdr = b''
    while len(hdr) < 8:
        c = s.recv(8 - len(hdr))
        if not c:
            raise EOFError('closed')
        hdr += c
    ver, typ, ln, xid = struct.unpack('!BBHI', hdr)
    body = b''
    while len(body) < ln - 8:
        c = s.recv(ln - 8 - len(body))
        if not c:
            raise EOFError('closed')
        body += c
    return ver, typ, xid, body

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(path)

# HELLO
s.sendall(struct.pack('!BBHI', 4, 0, 8, 1))
ver, typ, xid, body = recv_msg(s)
print('switch hello:', ver, typ, len(body))

# FEATURES_REQUEST
s.sendall(struct.pack('!BBHI', 4, 5, 8, 2))
while True:
    ver, typ, xid, body = recv_msg(s)
    print('msg:', typ, 'len', len(body))
    if typ == 6:
        break

# FLOW_MOD (experimenter action)
s.sendall(fm)

# BARRIER_REQUEST
s.sendall(struct.pack('!BBHI', 4, 20, 8, 3))
while True:
    ver, typ, xid, body = recv_msg(s)
    print('after flowmod msg:', typ, 'len', len(body))
    if typ == 21:
        break
    if typ == 1:  # OFPT_ERROR
        print('ERROR body:', body.hex())
s.close()
print('done')
