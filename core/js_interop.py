import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import time
from os import path

from env import DIR_PATH

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
        # Add a small delay to ensure server is up
        await asyncio.sleep(1)

    inp = json.dumps({"command": cmd, "body": params})
    loop = asyncio.get_event_loop()
    
    retry_count = 0
    max_retries = 3
    
    while retry_count < max_retries:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                await loop.sock_connect(client, COMETA_SOCK)
                await loop.sock_sendall(client, inp.encode('utf-8'))
                client.shutdown(socket.SHUT_WR)
                outp = await recv_until_delimeter(client, '\n'.encode('utf-8'))
                client.shutdown(socket.SHUT_RD)
            
            response = json.loads(outp.decode('utf-8'))

            if "error" in response:
                error_msg = response["error"]
                # Completely suppress "View initial.undefined" errors
                if "View initial.undefined is not set" in error_msg:
                    # Don't log anything for this specific error
                    
                    # For global views, return empty structure so calling code won't crash
                    if cmd == "fetchContractsGlobalViews":
                        result = {}
                        for item in params.get("idVersions", []):
                            contract_id = str(item.get("id"))
                            if contract_id:
                                # Empty but valid structure
                                result[contract_id] = {
                                    "initial": {},
                                    "global": {}
                                }
                        return result
                    # Generic fallback for other commands
                    return {"error": "contract_view_unavailable"}
                else:
                    logger.error(f'JS error: {error_msg}')
                    logger.error(f'Stack trace: {response["stack"]}')
                    raise Exception(error_msg)
            
            return response["response"]
        
        except (ConnectionRefusedError, FileNotFoundError, RuntimeError) as e:
            retry_count += 1
            logger.warning(f"JS interop connection error (attempt {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                # Try to restart the server
                start_js_interop_server()
                await asyncio.sleep(2)
            else:
                logger.error(f"Failed to connect to JS interop after {max_retries} attempts")
                raise
