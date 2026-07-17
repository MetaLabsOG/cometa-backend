import subprocess
import sys
from pathlib import Path


def test_collection_manager_import_does_not_initialize_runtime_settings() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    code = (
        "import sys; "
        "import flex.db.classes.collection_manager; "
        "from flex import db; "
        "assert type(db).__name__ == '_LazyCometaDatabase'; "
        "assert 'env' not in sys.modules"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repository_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
