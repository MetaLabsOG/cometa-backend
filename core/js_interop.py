import asyncio
import atexit
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from os import path

from env import DIR_PATH

COMETA_SOCK = '/tmp/cometa-js-interop.sock'
SOCKET_WAIT_TIMEOUT = 30  # seconds
RESTART_COOLDOWN = 10  # minimum seconds between restarts

logger = logging.getLogger(__name__)

_js_process: subprocess.Popen | None = None
_js_lock = threading.Lock()
_last_restart_time: float = 0


def _kill_js_process():
    """Kill the current JS interop process if it's running."""
    global _js_process
    if _js_process is None:
        return
    pid = _js_process.pid
    try:
        _js_process.kill()
        _js_process.wait(timeout=5)
        logger.info(f'Killed JS interop process (pid={pid})')
    except ProcessLookupError:
        logger.debug(f'JS interop process (pid={pid}) already dead')
    except subprocess.TimeoutExpired:
        logger.warning(f'JS interop process (pid={pid}) did not exit after kill')
    except Exception as e:
        logger.warning(f'Error killing JS interop process (pid={pid}): {e}')
    _js_process = None


def start_js_interop_server():
    """Start the JS interop Node.js server, killing any previous instance first.

    Thread-safe. Returns the subprocess.Popen object.
    """
    global _js_process, _last_restart_time

    with _js_lock:
        _kill_js_process()

        logger.info('Starting JS interop server')
        if path.exists(COMETA_SOCK):
            logger.info(f'Socket file {COMETA_SOCK} exists, cleaning...')
            os.unlink(COMETA_SOCK)

        jspath = path.join(DIR_PATH, "js", "index.js")
        _js_process = subprocess.Popen(
            [shutil.which("node"), jspath, COMETA_SOCK],
            encoding="utf-8",
        )

        deadline = time.monotonic() + SOCKET_WAIT_TIMEOUT
        while not path.exists(COMETA_SOCK):
            if time.monotonic() > deadline:
                _kill_js_process()
                raise RuntimeError(f'JS interop server failed to start within {SOCKET_WAIT_TIMEOUT}s')
            if _js_process.poll() is not None:
                rc = _js_process.returncode
                _js_process = None
                raise RuntimeError(f'JS interop server exited prematurely with code {rc}')
            time.sleep(0.1)

        _last_restart_time = time.monotonic()
        logger.info(f'JS interop server started (pid={_js_process.pid})')
        return _js_process


@contextmanager
def managed_js_interop_server():
    """Context manager that starts the JS interop server and cleans up on exit."""
    proc = start_js_interop_server()
    try:
        yield proc
    finally:
        _kill_js_process()
        if path.exists(COMETA_SOCK):
            try:
                os.unlink(COMETA_SOCK)
            except FileNotFoundError:
                pass


atexit.register(_kill_js_process)


MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB


async def recv_until_delimeter(s: socket.socket, delimeter: bytes, buf_size: int = 2048) -> bytes:
    loop = asyncio.get_running_loop()
    buf = b''
    while delimeter not in buf:
        chunk = await loop.sock_recv(s, buf_size)
        if not chunk:
            raise RuntimeError("socket closed during recv")
        buf += chunk
        if len(buf) > MAX_RESPONSE_SIZE:
            raise RuntimeError(f"JS interop response exceeded {MAX_RESPONSE_SIZE} bytes limit")
    res, _, _ = buf.partition(delimeter)
    return res


async def _restart_js_server():
    """Restart JS interop server from async context without blocking the event loop."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, start_js_interop_server)


async def calljs(cmd: str, **params):
    if not path.exists(COMETA_SOCK):
        logger.error(f'No Unix socket {COMETA_SOCK}; did you start js interop server?')
        await _restart_js_server()
        await asyncio.sleep(1)

    inp = json.dumps({"command": cmd, "body": params})
    loop = asyncio.get_running_loop()

    retry_count = 0
    max_retries = 3

    while retry_count < max_retries:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(30)
                client.setblocking(False)
                await loop.sock_connect(client, COMETA_SOCK)
                await loop.sock_sendall(client, inp.encode('utf-8'))
                client.shutdown(socket.SHUT_WR)
                outp = await asyncio.wait_for(
                    recv_until_delimeter(client, '\n'.encode('utf-8')),
                    timeout=30
                )
                client.shutdown(socket.SHUT_RD)

            response = json.loads(outp.decode('utf-8'))

            if "error" in response:
                error_msg = response["error"]
                # Completely suppress "View initial.undefined" errors
                if "View initial.undefined is not set" in error_msg:
                    # For global views, return empty structure so calling code won't crash
                    if cmd == "fetchContractsGlobalViews":
                        result = {}
                        for item in params.get("idVersions", []):
                            contract_id = str(item.get("id"))
                            if contract_id:
                                result[contract_id] = {
                                    "initial": {},
                                    "global": {}
                                }
                        return result
                    return {"error": "contract_view_unavailable"}
                else:
                    logger.error(f'JS error: {error_msg}')
                    logger.error(f'Stack trace: {response["stack"]}')
                    raise Exception(error_msg)

            return response["response"]

        except (ConnectionRefusedError, FileNotFoundError, RuntimeError, asyncio.TimeoutError) as e:
            retry_count += 1
            logger.warning(f"JS interop connection error (attempt {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                socket_gone = not path.exists(COMETA_SOCK)
                elapsed = time.monotonic() - _last_restart_time
                if not socket_gone and elapsed < RESTART_COOLDOWN:
                    logger.info(f"Skipping restart — last restart was {elapsed:.0f}s ago (cooldown {RESTART_COOLDOWN}s)")
                    await asyncio.sleep(2)
                else:
                    await _restart_js_server()
                    await asyncio.sleep(2)
            else:
                logger.error(f"Failed to connect to JS interop after {max_retries} attempts")
                raise
