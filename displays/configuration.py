"""Conservative, source-preserving editing of Omarchy's monitor declarations.

The existing monitors.lua is the authority. Only changed fields are replaced;
we never execute user Lua to discover its meaning or rewrite arbitrary code.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile

from adapter import DisplayError, lua_string


def tokens(source):
    """Lua lexical tokens with source offsets, excluding whitespace/comments."""
    result = []
    i = 0
    while i < len(source):
        if source[i].isspace():
            i += 1
            continue
        start = i
        comment = source.startswith('--', i)
        if comment:
            i += 2
        long = re.match(r'\[(=*)\[', source[i:])
        if long:
            end = source.find(']' + long[1] + ']', i + len(long[0]))
            if end < 0:
                raise DisplayError('Unterminated Lua long string/comment')
            i = end + len(long[1]) + 2
            if not comment:
                result.append((source[start:i], start, i))
            continue
        if comment:
            end = source.find('\n', i)
            i = len(source) if end < 0 else end
            continue
        if source[i] in ('"', "'"):
            quote = source[i]
            i += 1
            while i < len(source) and source[i] != quote:
                i += 2 if source[i] == '\\' else 1
            if i >= len(source):
                raise DisplayError('Unterminated Lua string')
            i += 1
        else:
            word = re.match(r'[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?', source[i:])
            i += len(word[0]) if word else 1
        result.append((source[start:i], start, i))
    return result


def declarations(source):
    ts = tokens(source)
    values = [t[0] for t in ts]
    # Conditional/generated rules cannot be safely inferred from live geometry.
    if any(v in ('if', 'for', 'while', 'repeat', 'function', 'do', 'goto') for v in values):
        raise DisplayError('Custom Lua control flow in monitors.lua cannot be edited automatically')
    rules = {}
    i = 0
    while i < len(ts):
        if values[i:i + 3] != ['hl', '.', 'monitor']:
            i += 1
            continue
        if values[i + 3:i + 5] != ['(', '{']:
            raise DisplayError('Use a literal hl.monitor({ ... }) declaration in monitors.lua')
        opening = i + 4
        j = opening + 1
        fields = {}
        while j < len(ts) and values[j] != '}':
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', values[j]) or values[j + 1:j + 2] != ['=']:
                raise DisplayError('Unsupported monitor table field in monitors.lua')
            key = values[j]
            start = j + 2
            j = start
            stack = []
            while j < len(ts):
                v = values[j]
                if not stack and v in (',', ';', '}'):
                    break
                if v in ('{', '(', '['):
                    stack.append(v)
                elif v in ('}', ')', ']'):
                    if not stack or stack.pop() != {'}': '{', ')': '(', ']': '['}[v]:
                        raise DisplayError('Unbalanced monitor expression')
                j += 1
            if j == start or j >= len(ts) or key in fields:
                raise DisplayError('Invalid or duplicate monitor field in monitors.lua')
            fields[key] = (ts[start][1], ts[j - 1][2])
            if values[j] in (',', ';'):
                j += 1
        if values[j:j + 2] != ['}', ')'] or 'output' not in fields:
            raise DisplayError('Monitor declaration needs a literal output selector')
        a, b = fields['output']
        selector = source[a:b]
        if len(selector) < 2 or selector[0] not in ('"', "'") or selector[-1] != selector[0] or '\\' in selector[1:-1] or selector[0] in selector[1:-1]:
            raise DisplayError('Computed monitor output selectors cannot be edited automatically')
        selector = selector[1:-1]
        if selector in rules:
            raise DisplayError('Multiple monitor declarations for ' + (selector or 'the fallback'))
        rules[selector] = dict(fields=fields, close=ts[j][1], last=values[j - 1])
        i = j + 2
    return rules


def replace(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            os.fchmod(f.fileno(), path.stat().st_mode & 0o777 if path.exists() else 0o600)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Configuration:
    def __init__(self, root=None):
        self.root = Path(root) if root else Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'hypr'
        self.path = (self.root / 'monitors.lua').resolve()

    def sources(self):
        """Follow literal user-module imports; ignore unused files and backups."""
        seen = {}
        def visit(path):
            path = path.resolve()
            if str(path) in seen or not path.exists():
                return
            source = path.read_text()
            seen[str(path)] = source
            ts = tokens(source)
            vs = [t[0] for t in ts]
            for i, value in enumerate(vs):
                if value != 'require':
                    continue
                j = i + 2 if vs[i + 1:i + 2] == ['('] else i + 1
                if j >= len(vs):
                    continue
                name = vs[j].strip('\"\'')
                if name.startswith('hypr.') and not name.startswith('hypr.hypertile') and re.fullmatch(r'hypr\.[\w.]+', name):
                    visit(self.root.parent / (name.replace('.', '/') + '.lua'))
        visit(self.root / 'hyprland.lua')
        return seen

    def plan(self, before, document):
        baseline = {d['connector']: d for d in before}
        changes = []
        for d in document['displays']:
            old = baseline.get(d['connector'], {})
            groups = {'mode': ('width', 'height', 'refresh'), 'position': ('x', 'y'),
                      'scale': ('scale',), 'transform': ('transform',), 'disabled': ('enabled',)}
            values = dict(mode=lua_string(f"{d['width']}x{d['height']}@{d['refresh']:.5f}"),
                          position=lua_string(f"{d['x']}x{d['y']}"), scale=str(d['scale']),
                          transform=str(d['transform']), disabled='false' if d['enabled'] else 'true')
            fields = {key: values[key] for key, names in groups.items()
                      if any(abs(float(d[n]) - float(old[n])) > (0.01 if n == 'refresh' else .0001 if n == 'scale' else 0)
                             if n in old else True for n in names)}
            target = d.get('mirror_of')
            source = next((m for m in document['displays'] if m['id'] == target), None)
            mirror = source['connector'] if source else ''
            old_mirror = old.get('mirror_connector') or ''
            if mirror != old_mirror or ('disabled' in fields and ('mirror_of' in d or old.get('mirror_of'))):
                fields['mirror'] = lua_string(mirror)
            if fields:
                changes.append((d, fields))
        if not changes:
            return None
        sources = self.sources()
        if str(self.path) not in sources:
            raise DisplayError(f'{self.path} must be loaded with require("hypr.monitors") before display settings can be saved')
        for path, source in sources.items():
            if path != str(self.path):
                vs = [t[0] for t in tokens(source)]
                if any(vs[i:i + 3] == ['hl', '.', 'monitor'] for i in range(len(vs))):
                    raise DisplayError(f'Display rules in {path} also control monitors. Move those rules to {self.path} to edit them here.')
        source = sources[str(self.path)]
        try:
            rules = declarations(source)
        except DisplayError as error:
            raise DisplayError(f'{self.path}: {error}') from error
        edits = []
        additions = []
        for d, fields in changes:
            connector = d['connector']
            rule = rules.get(connector) or rules.get('desc:' + d.get('description', ''))
            if rule and connector not in rules and d.get('ambiguous'):
                raise DisplayError(f'{self.path}: description rule matches multiple connections; use connector-specific rules')
            if rule:
                extra = []
                for key, value in fields.items():
                    if key in rule['fields']:
                        a, b = rule['fields'][key]
                        edits.append((a, b, value))
                    else:
                        extra.append(key + ' = ' + value)
                if extra:
                    prefix = '' if rule['last'] in ('{', ',', ';') else ', '
                    edits.append((rule['close'], rule['close'], prefix + ', '.join(extra) + ' '))
            else:
                # Inherit fallback expressions, rather than freezing its current
                # preferred mode, automatic placement or shared scale variable.
                inherited = {}
                if '' in rules:
                    inherited = {k: source[a:b] for k, (a, b) in rules['']['fields'].items() if k != 'output'}
                inherited.update(fields)
                additions.append('hl.monitor({ output = ' + lua_string(connector) + ', ' +
                                 ', '.join(k + ' = ' + v for k, v in inherited.items()) + ' })')
        updated = source
        for a, b, value in sorted(edits, reverse=True):
            updated = updated[:a] + value + updated[b:]
        if additions:
            updated = updated.rstrip() + '\n\n-- Display settings saved by Hypertile.\n' + '\n'.join(additions) + '\n'
        check = subprocess.run(['lua', '-e', 'local s=io.read("*a"); local f,e=load(s); if not f then io.stderr:write(e); os.exit(1) end'],
                               input=updated, text=True, capture_output=True, timeout=5)
        if check.returncode:
            raise DisplayError('Cannot save display configuration: ' + check.stderr.strip())
        return dict(path=str(self.path), before=source, after=updated, sources=sources)

    def commit(self, plan, before_write=None):
        if not plan:
            return
        if self.sources() != plan['sources']:
            raise DisplayError('Hyprland configuration changed during preview. Refresh and preview again.')
        path = Path(plan['path'])
        backup = path.with_name(path.name + '.hypertile.bak')
        if not backup.exists():
            replace(backup, plan['before'])
        if before_write:
            before_write()
        replace(path, plan['after'])

    def rollback(self, plan):
        if not plan:
            return []
        path = Path(plan['path'])
        try:
            current = path.read_text()
            if current == plan['after']:
                replace(path, plan['before'])
            elif current != plan['before']:
                return ['Display configuration changed externally; preserved ' + str(path)]
        except OSError as error:
            return [str(error)]
        return []
