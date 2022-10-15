import asyncio
import subprocess
import shutil
import socket
import json
import os
import time

from os import path

from core.constants import DIR_PATH
from env import settings

COMETA_SOCK = f'/tmp/cometa-js-interop-{settings.algo_network}.sock'

def start_js_interop_server():
    if path.exists(COMETA_SOCK):
        print(f'socket file {COMETA_SOCK} exists, cleaning...')
        os.unlink(COMETA_SOCK)

    jspath = path.join(DIR_PATH, "js", "index.js")
    proc = subprocess.Popen([shutil.which("node"), jspath, COMETA_SOCK], encoding="utf-8")
    
    # okay this is a HACK to achieve waiting for the node server to start fully
    # while also redirecting its stdin/stdout fully back to console (enabling debugging)
    while not path.exists(COMETA_SOCK):
        time.sleep(0.1)

    return proc

async def recv_until_delimeter(s: socket.socket, delimeter: bytes, buf_size: int = 2048) -> bytes:
    loop = asyncio.get_event_loop()
    buf = b''
    while delimeter not in buf:
        chunk = await loop.sock_recv(s, buf_size)
        if not chunk:
            raise RuntimeError("socket closed during recv")
        buf += chunk
    res, _, _ = buf.partition(delimeter)
    return res

async def calljs(cmd: str, **params):
    if not path.exists(COMETA_SOCK):
        raise Exception(f"No Unix socket {COMETA_SOCK}; did you start js interop server?")

    inp = json.dumps({"command": cmd, "body": params})
    loop = asyncio.get_event_loop()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        await loop.sock_connect(client, COMETA_SOCK)
        await loop.sock_sendall(client, inp.encode('utf-8'))
        client.shutdown(socket.SHUT_WR)
        outp = await recv_until_delimeter(client, '\n'.encode('utf-8'))
        client.shutdown(socket.SHUT_RD)
    
    response = json.loads(outp.decode('utf-8'))

    if "error" in response:
        print('js stack trace:', response["stack"])
        raise Exception(response["error"])
    
    return response["response"]
