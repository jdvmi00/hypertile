"""Resolve confirmed display intent before the session adapter restores windows."""
import copy
import json
import os
from pathlib import Path
import sys


def project(record):
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'hypertile/displays'
    path = state / 'confirmed.json'
    if not path.exists():
        return record
    # Display modules use sibling imports, as in the display service entry point.
    # Load them from their module directory so transitive imports also resolve.
    displays = str(Path(__file__).resolve().parent.parent / "displays")
    if displays not in sys.path:
        sys.path.insert(0, displays)
    from adapter import Adapter, match, runtime_mirrors
    from policy import project_session
    document = json.loads(path.read_text())
    adapter = Adapter()
    current = adapter.displays()
    document = runtime_mirrors(document, current)
    available = {}
    for saved in document.get('displays', []):
        actual = match(saved, current)
        if actual and actual['enabled'] and not actual.get('mirror_of') and not saved.get('mirror_of'):
            available[saved['id']] = actual['connector']
    fallback = json.loads(adapter.run('-j', 'getoption', 'general:layout')).get('str', 'dwindle')
    result = copy.deepcopy(record)
    result['desktop'] = project_session(record['desktop'], document, available, fallback=fallback)
    return result
