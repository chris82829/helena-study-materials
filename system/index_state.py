"""Small, atomic progress record for the explicit full-corpus index build."""
import json
from pathlib import Path
import tempfile
import time


def progress_path(database):
    path = Path(database)
    return path.with_suffix('.index.json')


def write_progress(database, completed, total, status, elapsed):
    path = progress_path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, suffix='.tmp', delete=False) as file:
        temporary = Path(file.name)
        json.dump({'completed': completed, 'total': total, 'status': status,
                   'elapsed_seconds': round(elapsed, 1), 'updated_at': time.time()}, file)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_progress(database, total, required=False):
    if not required:
        return {'required': False, 'status': 'ready', 'completed': total, 'total': total}
    try:
        result = json.loads(progress_path(database).read_text())
        if result['total'] != total:
            raise ValueError('Dataset changed')
        return {**result, 'required': True}
    except (OSError, ValueError, KeyError):
        return {'required': True, 'status': 'pending', 'completed': 0, 'total': total}
