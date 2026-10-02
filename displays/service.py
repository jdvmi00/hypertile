#!/usr/bin/env python3
"""Durable display previews with a watchdog independent of the overlay."""
import argparse
import contextlib
import copy
import fcntl
import json
import os
import re
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid

from adapter import Adapter, DisplayError, match, same, validate, independent, apply_order, lua_string
from policy import WorkspacePolicy, snapshot_rules, restore_rules, sync_rules, valid_workspace, selector
from configuration import Configuration


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex)
    try:
        with temp.open('x') as f:
            os.chmod(temp, 0o600)
            json.dump(value, f, indent=2, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def read(path, fallback=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return fallback


class Service:
    PREVIEW_SECONDS = 15

    def __init__(self, adapter=None, directory=None):
        self.adapter = adapter or Adapter()
        self.configuration = Configuration() if adapter is None else None
        self.directory = Path(directory) if directory else Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'hypertile/displays'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.pending_path = self.directory / 'pending.json'
        self.confirmed_path = self.directory / 'confirmed.json'
        self.power_path = self.directory / 'power.json'
        self.policy = WorkspacePolicy(self.adapter, self.directory)

    @contextlib.contextmanager
    def lock(self):
        with (self.directory / 'capture.lock').open('a') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            # CLI transactions and the long-lived watcher share this durable
            # policy state. Refresh only after acquiring the writer guard.
            if self.policy:
                self.policy.state = read(self.directory / 'workspace-runtime.json',
                                         dict(locations={}, available=[], suppressed=[]))
            yield

    def reconcile(self, document, reason):
        if self.policy:
            self.policy.reconcile(document, reason)

    def event(self):
        with self.lock():
            # The check belongs inside the same lock as all policy mutations.
            if self.pending_path.exists():
                return False
            self.reconcile(read(self.confirmed_path, dict(version=1, displays=[], workspaces={})), 'event')
            return True

    def catalog(self):
        self.settle_power()
        current = self.adapter.displays()
        confirmed = read(self.confirmed_path, dict(version=1, displays=[], workspaces={}))
        if self.policy:
            from policy import read_rules
            for workspace, layout in read_rules().items():
                confirmed.setdefault('workspaces', {}).setdefault(workspace, {})['layout'] = layout
        disconnected = []
        for saved in confirmed['displays']:
            actual = match(saved, current)
            if actual:
                # Stable saved references survive connector changes and a pair
                # of identical displays temporarily becoming one display.
                actual['id'] = saved['id']
                # Disabled-at-startup outputs have no initialized mode/geometry.
                # Keep the settings needed to enable them in the editor; live
                # enabled/power/topology state still comes from the compositor.
                if not actual['enabled']:
                    for key in ('width', 'height', 'refresh', 'scale', 'transform', 'x', 'y'):
                        if key in saved:
                            actual[key] = saved[key]
                for key in ('default_layout', 'initial_workspace', 'explicit_match', 'extended_position'):
                    if key in saved:
                        actual[key] = saved[key]
            if not actual:
                disconnected.append(dict(saved, connected=False, modes=[]))
        if self.configuration:
            for display in current:
                display['explicit_match'] = True
        ids = {d['connector']: d['id'] for d in current}
        for d in current:
            if d.get('mirror_connector'):
                d['mirror_of'] = ids.get(d['mirror_connector'], d.get('mirror_of'))
            if not d['enabled'] and (d['width'] <= 0 or d['height'] <= 0):
                mode = next((m for value in d['modes']
                             if (m := re.fullmatch(r'(\d+)x(\d+)@([\d.]+)Hz', value))), None)
                if mode:
                    d.update(width=int(mode[1]), height=int(mode[2]), refresh=float(mode[3]), scale=1, transform=0)
        current.extend(disconnected)
        return dict(version=1, displays=current, workspaces=self.adapter.workspaces(), confirmed=confirmed,
                    pending=read(self.pending_path), configuration=str(self.configuration.path) if self.configuration else None,
                    recovery=read(self.directory / 'recovery.json'), service_error=read(self.directory / 'daemon-error.json'))

    def preview(self, document, takeover=False, watchdog=True, migrate=False):
        with self.lock():
            return self._preview(document, takeover, watchdog, migrate)

    def _preview(self, document, takeover=False, watchdog=True, migrate=False, handoff=None, save_only=False):
        if self.pending_path.exists():
            raise DisplayError('A display preview is already active. Keep or revert it first.')
        scene_root = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'hypertile/scenes'
        if read(scene_root / 'state.json', {}).get('browse', {}).get('active'):
            raise DisplayError('Finish the layout preview before applying display changes.')
        status = read(self.directory.parent / 'sessions/status.json', {})
        if status.get('mode') == 'restoring':
            raise DisplayError('Wait for session restoration to finish before changing displays.')
        before = self.adapter.displays()
        known = read(self.confirmed_path, {}).get('displays', [])
        desired = validate(document, before, known=known)
        removed = self.validate_removals(document, before, known)
        remaining = {d['connector']: d for d in before}
        remaining.update({d['connector']: d for d in desired})
        # Newly enabled destinations are explicitly woken below. An already
        # enabled sleeping output must be woken before removing its controls.
        awake = {d['connector'] for d in before if d.get('awake', True) or not d['enabled']}
        if not save_only and not any(independent(d) and d['connector'] in awake for d in remaining.values()):
            raise DisplayError('Wake an extended display before disabling or mirroring the last awake display.')
        if self.policy:
            self.policy.validate_changes(document)
        document = copy.deepcopy(document)
        resolved = {d['id']: d for d in desired}
        for d in document['displays']:
            if d['id'] in resolved:
                d['connector'] = resolved[d['id']]['connector']
                # Preview, configuration writes and confirmed preferences
                # must describe the same normalized scale.
                d['scale'] = resolved[d['id']]['scale']
                old = match(d, before)
                if d.get('mirror_of') and old and independent(old) and not (handoff and d.get('extended_position')):
                    d['extended_position'] = dict(x=old['x'], y=old['y'])
        document.pop('takeover', None)
        baseline = before + [d for d in read(self.confirmed_path, {}).get('displays', [])
                             if not any(m['connector'] == d['connector'] for m in before)]
        config_plan = self.configuration.plan([] if migrate else baseline, document) if self.configuration else None
        if self.configuration:
            document['configuration_backed'] = True
        pending = dict(config_plan=config_plan, removed=removed, token=uuid.uuid4().hex, deadline=time.time() + self.PREVIEW_SECONDS, phase='applying',
                       before=before, workspaces=self.policy.capture_workspaces() if self.policy else self.adapter.workspaces(), document=document,
                       expected={d['connector']: d for d in before}, touched=[],
                       policy_state=copy.deepcopy(self.policy.state) if self.policy else None,
                       rule_files=snapshot_rules(document) if self.policy else [], rule_touched=[], handoff=handoff, save_only=save_only)
        atomic(self.pending_path, pending)
        if watchdog:
            try:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_watchdog', pending['token']],
                                 start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, env=dict(os.environ, HYPERTILE_DISPLAY_STATE=str(self.directory)))
            except Exception:
                self.pending_path.unlink(missing_ok=True)
                raise
        try:
            # Establish destinations first, move assigned workspaces, disable sources last.
            for d in sorted(desired, key=apply_order) if not save_only else []:
                if handoff and any(old['connector'] == d['connector'] and same(d, old) for old in before):
                    continue
                application = d
                if handoff and d['connector'] == handoff['target']:
                    from handoff import promotion
                    application = promotion(d, before)
                if not independent(d) and not pending.get('placed'):
                    if handoff:
                        self._move_handoff(pending)
                    self.reconcile(document, 'handoff' if handoff else 'preview')
                    pending['placed'] = True
                pending['touched'].append(d['connector'])
                pending['expected'][d['connector']] = application
                atomic(self.pending_path, pending)  # journal before each compositor mutation
                self.adapter.apply(application)
                old = next((m for m in before if m['connector'] == d['connector']), None)
                if handoff and independent(d) and old and not independent(old):
                    self.adapter.apply(application)
                if independent(d) and old and not old['enabled'] and not old.get('awake', True):
                    self.adapter.power(d['connector'], True)
                self.adapter.verify([application])
            if not save_only and not pending.get('placed'):
                self.reconcile(document, 'preview')
            if handoff:
                target = next(d for d in desired if d['connector'] == handoff['target'])
                pending['expected'][target['connector']] = target
                atomic(self.pending_path, pending)
                # Both displays cannot occupy the group's anchor while they are
                # independent. Anchor the new source after demoting the old one.
                self.adapter.apply(target)
                self.adapter.verify([target])
            actual = self.adapter.verify(desired)
            if not save_only:
                self._settle_power(actual)
            if handoff:
                self._focus_handoff(handoff, handoff['target'])
            # The countdown is time to look at the result, so it starts once
            # every output has settled rather than before the first modeset.
            pending.update(phase='preview', expected={d['connector']: d for d in actual}, deadline=time.time() + self.PREVIEW_SECONDS)
            atomic(self.pending_path, pending)
            return dict(token=pending['token'], deadline=pending['deadline'], seconds=max(0, pending['deadline'] - time.time()))
        except Exception:
            self._rollback(pending)
            raise

    def remove_display(self, identity, watchdog=True):
        """Forget one disconnected profile immediately, without a modeset."""
        with self.lock():
            if self.pending_path.exists():
                raise DisplayError('Keep or revert the display preview before removing a saved display.')
            catalog = self.catalog()
            selected = next((d for d in catalog['displays'] if d['id'] == identity), None)
            if not selected:
                raise DisplayError('Saved display is no longer available. Refresh and try again.')
            document = dict(version=1,
                            displays=[d for d in catalog['displays'] if d['id'] != identity],
                            workspaces=copy.deepcopy(catalog['confirmed'].get('workspaces', {})),
                            removed_displays=[identity])
            for preference in document['workspaces'].values():
                if preference.get('monitor') == identity:
                    preference['monitor'] = None
            # Reuse the recovery journal and atomic save, but apply no preview
            # geometry and return only after the save is durably committed.
            transaction = self._preview(document, watchdog=watchdog, save_only=True)
            self._keep(transaction['token'])
            return dict(removed=identity, connector=selected['connector'],
                        message=selected['connector'] + ' saved display removed.')

    def use_display(self, connector, watchdog=True):
        """Switch and save a mirror group's source as one recoverable transaction."""
        from handoff import plan, source_for
        with self.lock():
            if self.pending_path.exists():
                raise DisplayError('Keep or revert the display preview before switching displays.')
            catalog = self.catalog()
            active = json.loads(self.adapter.run('-j', 'activeworkspace'))
            if connector == 'next':
                _, _, group = source_for(catalog['displays'], active.get('monitor'))
                choices = [d for d in group if d.get('connected', True) and d['enabled'] and d.get('awake', True)]
                current = next(i for i, d in enumerate(choices) if d['connector'] == active.get('monitor'))
                connector = choices[(current + 1) % len(choices)]['connector']
            document = dict(version=1, displays=catalog['displays'],
                            workspaces=catalog['confirmed'].get('workspaces', {}))
            selected, source, _ = source_for(document['displays'], connector)
            if selected['id'] == source['id']:
                return dict(used=True, connector=connector, message='The desktop is already sized for ' + connector + '.')
            desired, previous = plan(document, connector)
            window = json.loads(self.adapter.run('-j', 'activewindow'))
            handoff = dict(source=previous, target=connector, active=active, window=window.get('address'),
                           visible=source.get('active_workspace') or (active if active.get('monitor') == previous else {}))
            preview = self._preview(desired, watchdog=watchdog, handoff=handoff)
            self._keep(preview['token'])
            return dict(used=True, connector=connector, previous_source=previous,
                        message='Desktop sized for ' + connector + '. Other displays in the group mirror it.')

    @staticmethod
    def _handoff_workspace(workspace):
        name = workspace.get('name', '')
        return name if name.startswith('special:') else selector(workspace)

    def _move_handoff(self, pending):
        handoff = pending['handoff']
        existing = {self._handoff_workspace(w) for w in self.adapter.workspaces()}
        moved = []
        for workspace in pending['workspaces']:
            key = self._handoff_workspace(workspace)
            if workspace.get('monitor') == handoff['source'] and key in existing:
                self.adapter.move(key, handoff['target'])
                moved.append(key)
        actual = {self._handoff_workspace(w): w.get('monitor') for w in self.adapter.workspaces()}
        if any(actual.get(key) != handoff['target'] for key in moved):
            raise DisplayError('Hyprland did not move the shared desktop. Restoring the previous display.')

    def _focus_handoff(self, handoff, source):
        # Restore the group's visible workspace, then the user's global focus.
        visible = handoff.get('visible', {})
        if visible.get('name') and not visible['name'].startswith('special:'):
            self.adapter.dispatch('focus', '{monitor=' + lua_string(source) + '}')
            self.adapter.dispatch('focus', '{workspace=' + lua_string(selector(visible)) + '}')
        active = handoff.get('active', {})
        if active.get('name'):
            monitor = source if active.get('monitor') == handoff['source'] else active.get('monitor')
            if monitor and any(d['connector'] == monitor and independent(d) for d in self.adapter.displays()):
                self.adapter.dispatch('focus', '{monitor=' + lua_string(monitor) + '}')
                self.adapter.dispatch('focus', '{workspace=' + lua_string(selector(active)) + '}')
        if handoff.get('window'):
            self.adapter.dispatch('focus', '{window=' + lua_string('address:' + handoff['window']) + '}')

    def validate_removals(self, document, current, known):
        ids = document.get('removed_displays', [])
        if not isinstance(ids, list) or any(not isinstance(identity, str) for identity in ids) or len(set(ids)) != len(ids):
            raise DisplayError('Removed displays must be a list of unique saved display ids.')
        saved = {d['id']: d for d in known}
        remaining = {d['id'] for d in document['displays']}
        removed = []
        for identity in ids:
            d = saved.get(identity)
            if not d or identity in remaining:
                raise DisplayError('Removed display is no longer available for removal. Reset the draft and try again.')
            if match(d, current) or any(m['connector'] == d['connector'] for m in current):
                raise DisplayError('Cannot remove a connected display or a connector now in use: ' + d['connector'] + '. Reset the draft; use Disable to turn it off.')
            if any(m['connector'] == d['connector'] for m in document['displays']):
                raise DisplayError('Another saved display uses ' + d['connector'] + '. Match or remove that stale entry first.')
            if any(m.get('mirror_of') == identity for m in document['displays']):
                raise DisplayError('Remove saved mirrors first or choose another mirror source before removing ' + d['connector'] + '.')
            if any(p.get('monitor') == identity for p in document.get('workspaces', {}).values()):
                raise DisplayError('Clear workspace placement references before removing ' + d['connector'] + '; preserve their layouts.')
            removed.append(d)
        return removed

    def _rollback(self, pending):
        current = self.adapter.displays()
        by_connector = {d['connector']: d for d in current}
        report = dict(reason='reverted', fallback=False, external=[], errors=[])
        rule_files = [saved for saved in pending.get('rule_files', [])
                      if 'rule_touched' not in pending or saved.get('workspace') in pending['rule_touched']]
        rule_errors = restore_rules(rule_files) if pending.get('phase') in ('committing', 'recovery-needed') else []
        if self.configuration and pending.get('config_touched'):
            rule_errors.extend(self.configuration.rollback(pending.get('config_plan')))
            if not rule_errors:
                try:
                    self.adapter.reload()
                except Exception as error:
                    rule_errors.append(str(error))
        report['errors'].extend(rule_errors)
        restore = []
        for old in pending['before']:
            name = old['connector']
            actual = by_connector.get(name)
            if name not in pending['touched'] or not actual:
                continue
            expected = pending['expected'].get(name)
            if expected and not same(actual, expected) and not same(actual, old):
                report['external'].append(name)
                continue
            restore.append(old)
        anchors = []
        for d in sorted(restore, key=apply_order):
            # Never disable the only output left after a physical unplug.
            live = self.adapter.displays()
            if not d['enabled'] and not any(independent(x) and x['connector'] != d['connector'] for x in live):
                report['fallback'] = True
                continue
            try:
                was_mirror = any(x['connector'] == d['connector'] and not independent(x) for x in live)
                if pending.get('handoff') and independent(d) and was_mirror:
                    from handoff import promotion
                    anchors.append(d)
                    d = promotion(d, live)
                if d.get('mirror_connector') and not any(x['connector'] == d['mirror_connector'] and independent(x) for x in live):
                    d = dict(d, mirror_of=None, mirror_connector=None)
                    report['fallback'] = True
                self.adapter.apply(d)
                if pending.get('handoff') and independent(d) and was_mirror:
                    self.adapter.apply(d)
                self.adapter.verify([d])
            except Exception as error:
                report['errors'].append(str(error))
        for d in anchors:
            try:
                self.adapter.apply(d)
                self.adapter.verify([d])
            except Exception as error:
                report['errors'].append(str(error))
        live = self.adapter.displays()
        if live and not any(independent(d) for d in live):
            rescue = dict(live[0], enabled=True, mirror_of=None, mirror_connector=None, scale=1, transform=0, x=0, y=0)
            if rescue['modes']:
                import re
                m = re.fullmatch(r'(\d+)x(\d+)@([\d.]+)Hz', rescue['modes'][0])
                if m:
                    rescue.update(width=int(m[1]), height=int(m[2]), refresh=float(m[3]))
            self.adapter.apply(rescue)
            self.adapter.verify([rescue])
            report['fallback'] = True
        enabled = {d['connector'] for d in self.adapter.displays() if independent(d)}
        key_for = self._handoff_workspace if pending.get('handoff') else selector
        existing = {key_for(w) for w in self.adapter.workspaces()}
        for w in pending['workspaces']:
            key = key_for(w)
            # Hyprland destroys empty workspaces during output evacuation. They
            # have no windows to recover and cannot be moved after rollback.
            if key not in existing:
                continue
            if w.get('monitor') in enabled and w['monitor'] not in report['external']:
                try:
                    self.adapter.move(key, w['monitor'])
                except Exception as error:
                    report['errors'].append(str(error))
            elif w.get('monitor') not in enabled:
                report['fallback'] = True
        if self.policy:
            try:
                if pending.get('policy_state') is not None:
                    self.policy.state = pending['policy_state']
                    self.policy._save_runtime()
                if hasattr(self.policy, 'restore_layouts'):
                    self.policy.restore_layouts(pending['workspaces'])
            except Exception as error:
                report['errors'].append(str(error))
        if pending.get('handoff'):
            try:
                self._focus_handoff(pending['handoff'], pending['handoff']['source'])
            except Exception as error:
                report['errors'].append(str(error))
        atomic(self.directory / 'recovery.json', report)
        if rule_errors:
            pending['phase'] = 'recovery-needed'
            atomic(self.pending_path, pending)
        else:
            self.pending_path.unlink(missing_ok=True)
            (self.directory / 'staged.json').unlink(missing_ok=True)
        return report

    def revert(self, token=None, expired_only=False):
        with self.lock():
            pending = read(self.pending_path)
            if not pending:
                return dict(reason='no-preview')
            if read(self.confirmed_path, {}).get('_transaction') == pending['token']:
                self.pending_path.unlink(missing_ok=True)
                (self.directory / 'staged.json').unlink(missing_ok=True)
                return dict(reason='already-confirmed')
            if token and token != pending['token']:
                raise DisplayError('Preview token no longer matches.')
            # Application holds this lock and can extend the countdown after
            # the watchdog observed its initial deadline. Check again here.
            if expired_only and time.time() < pending['deadline']:
                return dict(reason='not-expired')
            return self._rollback(pending)

    def keep(self, token):
        with self.lock():
            return self._keep(token)

    def _keep(self, token):
        pending = read(self.pending_path)
        if not pending or pending['token'] != token:
            raise DisplayError('Preview no longer exists.')
        if time.time() >= pending['deadline']:
            self._rollback(pending)
            raise DisplayError('Preview expired and was reverted.')
        if pending['phase'] != 'preview':
            raise DisplayError('Display changes are still being applied.')
        try:
            # A screen can reconnect while the user inspects the preview.
            # Recheck immediately before any durable preferences/config writes.
            self.validate_removals(pending['document'], self.adapter.displays(), pending.get('removed', []))
            self.adapter.verify([d for d in pending['expected'].values() if d['connector'] in pending['touched']])
        except Exception:
            self._rollback(pending)
            raise
        # Keep is a recoverable transaction: journal precedes all rule writes,
        # and the confirmed token is the single durable commit point.
        pending['phase'] = 'committing'
        atomic(self.pending_path, pending)
        staged_path = self.directory / 'staged.json'
        def before_rule(key):
            pending['rule_touched'].append(key)
            atomic(self.pending_path, pending)
        try:
            atomic(staged_path, pending['document'])
            if self.policy:
                self.policy.commit(pending['document'], preferences_path=staged_path, before_rule=before_rule)
            sync_rules(pending.get('rule_files', []))
            if self.configuration and pending.get('config_plan'):
                def before_config():
                    self.validate_removals(pending['document'], self.adapter.displays(), pending.get('removed', []))
                    pending['config_touched'] = True
                    atomic(self.pending_path, pending)
                self.configuration.commit(pending['config_plan'], before_write=before_config)
                self.adapter.reload()
                self.adapter.verify([d for d in pending['expected'].values()
                                     if pending.get('save_only') or d['connector'] in pending['touched']])
                if not pending.get('save_only'):
                    self.reconcile(pending['document'], 'keep')
            confirmed = dict(pending['document'], _transaction=token)
            confirmed.pop('removed_displays', None)
            atomic(self.confirmed_path, confirmed)
        except Exception:
            # An fsync failure may occur after replace; inspect the durable
            # marker before deciding whether rollback is still permissible.
            if read(self.confirmed_path, {}).get('_transaction') != token:
                self._rollback(pending)
            raise
        self.pending_path.unlink(missing_ok=True)
        staged_path.unlink(missing_ok=True)
        return dict(kept=True)

    def setup(self, offline=False):
        """Adopt existing config without changing it; migrate legacy saved intent once."""
        if not self.configuration:
            return dict(configured=False)
        with self.lock():
            if self.pending_path.exists():
                return dict(configured=False, preview_active=True)
            document = read(self.confirmed_path, dict(version=1, displays=[], workspaces={}))
            if document.get('configuration_backed'):
                return dict(configured=True)
            if not document['displays']:
                document['configuration_backed'] = True
                document.pop('takeover', None)
                atomic(self.confirmed_path, document)
                return dict(configured=True)
        if offline:
            return dict(configured=False, migration_pending=True)
        # Legacy geometry must be persisted before retiring its replay path.
        preview = self.preview(document, migrate=True)
        self.keep(preview['token'])
        return dict(configured=True, migrated=True)

    def restore(self, reason='restore'):
        if self.configuration and not self.pending_path.exists():
            self.setup()
        with self.lock():
            pending = read(self.pending_path)
            if pending:
                if reason in ('configreload', 'reconnect'):
                    return dict(restored=False, preview_active=True)
                if read(self.confirmed_path, {}).get('_transaction') == pending['token']:
                    self.pending_path.unlink(missing_ok=True)
                    (self.directory / 'staged.json').unlink(missing_ok=True)
                else:
                    return self._rollback(pending)
            document = read(self.confirmed_path)
            if not document:
                return dict(restored=False)
            current = self.adapter.displays()
            recovery = dict(reason=reason, fallback=False, errors=[])
            try:
                desired = [] if document.get('configuration_backed') else validate(document, current, known=document['displays'])
            except DisplayError as error:
                # A cable/backend can expose different modes after reconnect. Preserve
                # confirmed intent and keep the compositor's currently usable desktop.
                recovery.update(fallback=True, errors=[str(error)])
                desired = []
            before_workspaces = self.policy.capture_workspaces() if self.policy else self.adapter.workspaces()
            applied = []
            try:
                for d in sorted(desired, key=apply_order):
                    applied.append(d)
                    self.adapter.apply(d)
                    self.adapter.verify([d])
                self.reconcile(document, reason)
            except Exception as error:
                rollback = dict(before=current, workspaces=before_workspaces,
                                expected={d['connector']: d for d in applied},
                                touched=[d['connector'] for d in applied])
                recovery = self._rollback(rollback)
                recovery.update(reason=reason, fallback=True)
                recovery['errors'].append(str(error))
            live = self.adapter.displays()
            if live and not any(independent(d) for d in live):
                # Reuse recovery's safe-mode rescue when no remaining output is usable.
                self._rollback(dict(before=[], workspaces=[], expected={}, touched=[]))
                recovery['fallback'] = True
            atomic(self.directory / 'recovery.json', recovery)
            return dict(restored=bool(desired) and not recovery['errors'], **recovery)

    def stop(self, timeout=20):
        pid = read(self.directory / 'daemon.json', {}).get('pid')
        if pid:
            try:
                command = Path(f'/proc/{pid}/cmdline').read_bytes()
                if b'hypertile-displays' in command or str(Path(__file__).resolve()).encode() in command:
                    os.kill(pid, signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError):
                pass
        deadline = time.monotonic() + timeout
        with (self.directory / 'daemon.lock').open('a') as guard:
            while True:
                try:
                    fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise DisplayError('Display service did not stop within ' + str(timeout) +
                                           ' seconds. Runtime files must not be replaced while its writer lock is held.')
                    time.sleep(min(.1, max(.001, deadline - time.monotonic())))
            # The daemon is gone; finish any independently journalled preview.
            return self.revert()

    def wallpaper(self, request=None):
        import wallpaper
        if request is None:
            return dict(settings=wallpaper.load())
        document = wallpaper.validate(request.get('settings'))
        with self.lock():
            if self.pending_path.exists():
                raise DisplayError('Keep or revert the display preview before changing wallpaper.')
            current = wallpaper.load()
            if request.get('previous') != current:
                raise DisplayError('Wallpaper settings changed elsewhere. Refresh before applying.')
            known = {d['connector'] for d in self.adapter.displays()}
            known.update(d['connector'] for d in read(self.confirmed_path, {'displays': []})['displays'])
            known.update(o for g in current['groups'] for o in g['outputs'])
            if any(o not in known for g in document['groups'] for o in g['outputs']):
                raise DisplayError('A selected display is no longer available. Refresh before applying.')
            # Validate/install the renderer before committing preference changes.
            renderer, reload = wallpaper.install_renderer()
            atomic(wallpaper.config_path(), document)
            if reload:
                wallpaper.reload_shell_later()
            return dict(settings=document, renderer=renderer, message='Wallpaper groups applied and saved.')

    def show_workspace(self, connector, workspace):
        if not valid_workspace(workspace) or (workspace.isdigit() and int(workspace) > 2147483647):
            raise DisplayError('Workspace must be a positive number or name:<name>.')
        with self.lock():
            if self.pending_path.exists():
                raise DisplayError('Keep or revert the display preview before showing a workspace.')
            target = next((d for d in self.adapter.displays() if d['connector'] == connector), None)
            if not target or not independent(target) or not target.get('awake', True):
                raise DisplayError('Choose a connected, enabled, awake extended display.')
            existing = next((w for w in self.adapter.workspaces() if selector(w) == workspace), None)
            if existing and existing.get('monitor') != connector:
                self.adapter.move(workspace, connector)
            self.adapter.dispatch('focus', '{monitor=' + lua_string(connector) + '}')
            self.adapter.dispatch('focus', '{workspace=' + lua_string(workspace) + '}')
            actual = json.loads(self.adapter.run('-j', 'activeworkspace'))
            if selector(actual) != workspace or actual.get('monitor') != connector:
                raise DisplayError('Hyprland did not show the requested workspace on this display.')
            return dict(message='Showing workspace ' + workspace.removeprefix('name:') + ' on ' + connector + '.',
                        workspace=workspace, connector=connector)

    def power(self, connector, awake):
        with self.lock():
            if self.pending_path.exists():
                raise DisplayError('Keep or revert the display preview before changing power.')
            displays = self.adapter.displays()
            if connector and not any(d['connector'] == connector and d['enabled'] for d in displays):
                raise DisplayError('Choose a connected, enabled display.')
            if not awake:
                self._guard_wake(displays, connector)
            self.adapter.power(connector, awake)
            for _ in range(15):
                targets = [d for d in self.adapter.displays() if d['enabled'] and (not connector or d['connector'] == connector)]
                if targets and all(d.get('awake') == awake for d in targets):
                    break
                time.sleep(.1)
            else:
                raise DisplayError('Hyprland did not confirm the requested display power state.')
            self._settle_power()
            return dict(awake=awake, connector=connector)

    def _guard_wake(self, displays, connector):
        # Hyprland tracks DPMS as one global state, so once any output sleeps a key
        # press or mouse move with the wake options on turns every output back on.
        # Hold the options off while another output stays awake; when the last
        # awake output sleeps, guarantee a keyboard path back instead. The original
        # values are remembered until every output is awake again.
        guard = read(self.power_path) or dict(original=self.adapter.wake_options())
        others_awake = bool(connector) and any(independent(d) and d.get('awake', True) and d['connector'] != connector for d in displays)
        guard['apply'] = {name: False for name in self.adapter.WAKE_OPTIONS} if others_awake \
            else dict(guard['original'], key_press_enables_dpms=True)
        atomic(self.power_path, guard)
        self.adapter.set_wake_options(guard['apply'])

    def settle_power(self):
        if not self.power_path.exists():
            return False
        with self.lock():
            return self._settle_power()

    def _settle_power(self, displays=None):
        """Restore the wake options once every output is awake, however it woke;
        re-assert them while something sleeps, since a config reload resets them."""
        guard = read(self.power_path)
        if not guard:
            return False
        displays = self.adapter.displays() if displays is None else displays
        if all(d.get('awake', True) for d in displays if d['enabled']):
            self.adapter.set_wake_options(guard['original'])
            self.power_path.unlink(missing_ok=True)
        else:
            # Unplugging/disabling the awake output must not leave the sleeping
            # desktop with both input wake paths held off. Recompute on topology
            # changes and after reload, rather than replaying the old guard.
            options = {name: False for name in self.adapter.WAKE_OPTIONS} \
                if any(independent(d) and d.get('awake', True) for d in displays) \
                else dict(guard['original'], key_press_enables_dpms=True)
            if guard['apply'] != options:
                guard['apply'] = options
                atomic(self.power_path, guard)
            if self.adapter.wake_options() != options:
                self.adapter.set_wake_options(options)
        return True


def main():
    p = argparse.ArgumentParser(description='Arrange displays with a crash-safe 15-second preview. All results are JSON.')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('list', 'status', 'restore', 'recover', 'watch', 'daemon', 'stop', 'setup'):
        parser = sub.add_parser(name)
        if name == 'setup':
            parser.add_argument('--offline', action='store_true')
        if name in ('list', 'status'):
            parser.add_argument('--json', action='store_true')
    wallpaper = sub.add_parser('wallpaper')
    wallpaper.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    wallpaper.add_argument('--json', help='Apply settings and previous settings as JSON; - reads stdin')
    sub.add_parser('identify').add_argument('connector', nargs='?')
    preview = sub.add_parser('preview')
    preview.add_argument('--json', required=True, help='Version 1 display settings JSON; use - for stdin')
    preview.add_argument('--takeover', action='store_true', help=argparse.SUPPRESS)
    sub.add_parser('keep').add_argument('token')
    sub.add_parser('revert').add_argument('token', nargs='?')
    show = sub.add_parser('show-workspace')
    show.add_argument('connector')
    show.add_argument('workspace')
    sub.add_parser('use-display', help='Size a mirror group for this display and save immediately').add_argument('connector', help='Output connector, or next to cycle the focused mirror group')
    sub.add_parser('remove-display', help='Forget a disconnected display immediately').add_argument('identity', help='Saved display id from display list')
    sub.add_parser('sleep').add_argument('connector')
    sub.add_parser('wake').add_argument('connector', nargs='?', default='')
    sub.add_parser('_watchdog').add_argument('token')
    args = p.parse_args()
    try:
        service = Service(directory=os.environ.get('HYPERTILE_DISPLAY_STATE'))
        if args.command in ('list', 'status'):
            result = service.catalog()
        elif args.command == 'preview':
            result = service.preview(json.loads(sys.stdin.read() if args.json == '-' else args.json), args.takeover)
        elif args.command == 'keep':
            result = service.keep(args.token)
        elif args.command in ('revert', 'recover'):
            result = service.revert(getattr(args, 'token', None))
        elif args.command == 'setup':
            result = service.setup(offline=args.offline)
        elif args.command == 'restore':
            result = service.restore()
        elif args.command == 'wallpaper':
            import wallpaper
            request = json.loads(sys.stdin.read() if args.json == '-' else args.json) if args.json else None
            result = wallpaper.apply_detached(request) if request is not None and not args.worker else service.wallpaper(request)
        elif args.command == 'show-workspace':
            result = service.show_workspace(args.connector, args.workspace)
        elif args.command == 'use-display':
            result = service.use_display(args.connector)
        elif args.command == 'remove-display':
            result = service.remove_display(args.identity)
        elif args.command in ('sleep', 'wake'):
            result = service.power(args.connector, args.command == 'wake')
        elif args.command == '_watchdog':
            while True:
                pending = read(service.pending_path)
                if not pending or pending['token'] != args.token:
                    return
                if time.time() >= pending['deadline']:
                    if service.revert(args.token, expired_only=True)['reason'] != 'not-expired':
                        return
                time.sleep(min(.25, max(.01, pending['deadline'] - time.time())))
        elif args.command == 'stop':
            result = service.stop()
        elif args.command == 'identify':
            shell = os.environ.get('HYPERTILE_SHELL_BIN', 'omarchy-shell')
            identified = subprocess.run([shell, 'hypertile', 'displayIdentify', args.connector or ''],
                                        capture_output=True, text=True, timeout=5)
            if identified.returncode:
                raise DisplayError('Open the Hypertile overlay, then run identify again to show matching labels on every screen.')
            result = dict(identified=True, connector=args.connector or None)
        else:
            daemon(service)
            return
        print(json.dumps(result))
    except (DisplayError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(error=str(error))))
        sys.exit(1)


class Watcher:
    """Consult the compositor only when socket2 reports something that can move
    a workspace or change an output, on a slow safety poll, or while a sleeping
    output needs its wake options settled. An idle desktop then costs nothing:
    the earlier half-second poll spawned five processes and fsynced a file on
    every tick."""
    RELEVANT = ('configreloaded', 'monitoradded', 'monitorremoved', 'createworkspace',
                'destroyworkspace', 'moveworkspace', 'renameworkspace')

    def __init__(self, service, polling=False, interval=5.0):
        self.service = service
        self.interval = .5 if polling else interval
        self.previous = None
        self.last = None

    def tick(self, lines, now):
        names = {line.split('>>', 1)[0] for line in lines}
        reloaded = 'configreloaded' in names
        due = self.last is None or now - self.last >= self.interval
        if not (reloaded or due or self.service.power_path.exists()
                or any(name.startswith(self.RELEVANT) for name in names)):
            return False
        self.last = now
        service = self.service
        current = service.adapter.displays()
        topology = tuple((d['id'], d['connector'], d['enabled'], d.get('mirror_connector')) for d in current)
        if not service.pending_path.exists():
            if reloaded:
                service.restore('configreload')
            elif self.previous is not None and topology != self.previous:
                service.restore('reconnect')
            elif service.policy:
                service.event()
        service.settle_power()
        self.previous = topology
        return True


def daemon(service):
    # A separate per-preview watchdog survives daemon termination and shell crashes.
    with (service.directory / 'daemon.lock').open('a') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        atomic(service.directory / 'daemon.json', dict(pid=os.getpid()))
        stopping = False
        def stop(*_):
            nonlocal stopping
            stopping = True
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        if service.pending_path.exists():
            service.revert()
        events = None
        event_buffer = ''
        try:
            events = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            events.connect(str(Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / 'hypr' / os.environ['HYPRLAND_INSTANCE_SIGNATURE'] / '.socket2.sock'))
            events.setblocking(False)
        except (OSError, KeyError):
            if events:
                events.close()
            events = None
        watcher = Watcher(service, polling=events is None)
        while not stopping:
            try:
                lines = []
                if events:
                    try:
                        data = events.recv(65536)
                        if not data:
                            raise OSError('Hyprland event socket closed')
                        event_buffer += data.decode(errors='replace')
                        parts = event_buffer.split('\n')
                        event_buffer = parts.pop()
                        lines = parts
                    except BlockingIOError:
                        pass
                    except OSError:
                        events.close()
                        events = None
                        watcher.interval = .5
                watcher.tick(lines, time.monotonic())
            except Exception as error:
                atomic(service.directory / 'daemon-error.json', dict(error=str(error), time=time.time()))
            time.sleep(.5)
        service.revert()
        (service.directory / 'daemon.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
