import shutil
import subprocess
import json

from os import path
from env import DIR_PATH

def calljs(cmd: str, params: dict):
    jspath = path.join(DIR_PATH, "js", "index.js")
    inp = json.dumps(params)
    res = subprocess.run(["node", jspath, cmd], input=inp, capture_output=True, text=True)
    response = res.stdout
    return json.loads(response)