import shutil
import subprocess
import json
import os

from os import path
from env import DIR_PATH

# TODO: Loading up Reach for each interop call is wasteful and stupid. Should spawn 1 process
# per the backend lifecycle and continually communicate with it. But it's not super necessary right now.
# TODO: will need to create a writeout pipe separately for each request anyway.
def calljs(cmd: str, **params):
    jspath = path.join(DIR_PATH, "js", "index.js")
    inp = json.dumps(params)

    # create a pipe (stdout gets clogged by Reach console logs)
    fifo_path = "/tmp/.cometa_js_interop"
    if not path.exists(fifo_path):
        os.mkfifo(fifo_path)

    with subprocess.Popen(["node", jspath, fifo_path, cmd], stdin=subprocess.PIPE, encoding='utf-8') as proc:
        proc.stdin.write(inp)
        proc.stdin.close()
        with open(fifo_path, 'r') as f:
            output = f.read()

    os.unlink(fifo_path)
    response = json.loads(output)

    if "error" in response:
        print('js stack trace:', response["stack"])
        raise Exception(response["error"])
    
    return response["response"]