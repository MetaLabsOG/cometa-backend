import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import time
from os import path

from core.constants import DIR_PATH
from env import settings

COMETA_SOCK = f'/tmp/cometa-js-interop.sock'

logger = logging.getLogger(__name__)


def start_js_interop_server():
    logger.info('Starting js interop server')
    if path.exists(COMETA_SOCK):
        logger.info(f'Socket file {COMETA_SOCK} exists, cleaning...')
        os.unlink(COMETA_SOCK)

    jspath = path.join(DIR_PATH, "js", "index.js")
    proc = subprocess.Popen([shutil.which("node"), jspath, COMETA_SOCK], encoding="utf-8")
    
    # okay this is a HACK to achieve waiting for the node server to start fully
    # while also redirecting its stdin/stdout fully back to console (enabling debugging)
    while not path.exists(COMETA_SOCK):
        time.sleep(0.1)

    logger.info(f'Socket file {COMETA_SOCK} opened!')

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
        logger.error(f'No Unix socket {COMETA_SOCK}; did you start js interop server?')
        start_js_interop_server()

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
        logger.error(f'js error: {response["error"]}')
        logger.error(f'js stack trace: {response["stack"]}')
        raise Exception(response["error"])
    
    return response["response"]
