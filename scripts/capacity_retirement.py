"""Retire one signup slot: stop it, revoke its credentials, delete its objects, wipe its files, verify. Fails closed.

Runs only inside the capacity controller, and only when the installation's site configuration sets
allowSlotRetirement (default off). The gateway asks by writing policy/retirements/<slot>.json after an
administrator typed the account name; the controller answers in inventory/retirements/<slot>.json.

Guarantees:
  * The slot leaves the published pool and is marked retiring BEFORE anything is deleted, so a later failure
    can never hand its storage to another account. A slot is never reused: a replacement is a new random identity.
  * Only objects named by the slot's own generator are touched, and each must carry the provisioner's label.
  * Files are deleted only below the exact private directory of this identity; symbolic links are removed, never followed.
  * Any failed or unverifiable step quarantines the slot. Errors are fixed texts with no file names or contents.
  * Admin and banking slots are refused (site config protectedSlots) and nothing outside the named slot is touched.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import time

from capacity_controller import atomic_json, read_json, utc

SLOT = re.compile(r'cap-[a-f0-9]{16}-01')
REQUEST = re.compile(r'(cap-[a-f0-9]{16}-01)\.json')
ACCOUNT = re.compile(r'[a-z0-9_.-]{3,30}')
OWNED_LABEL = 'dsh.bot.or.th/capacity-managed'
FINAL = ('done', 'quarantined', 'refused')


class Refused(Exception):
    """The request is not acceptable; nothing was changed."""


class StepFailed(Exception):
    """A step could not be completed or verified; the message is a fixed text."""


def identity_of(slot):
    return hashlib.sha256(slot.encode()).hexdigest()[:16]


class Context:
    """What the controller supplies. The real one is built by Worker.retirement_context()."""
    central = None            # Path: central storage mount
    services = None           # Path: service-control mount
    sleep = staticmethod(time.sleep)
    monotonic = staticmethod(time.monotonic)

    def names(self, slot):
        """Exact object names of the slot: {'deployments','services','claims','secrets'} -> [name]."""
        raise NotImplementedError

    def get(self, kind, name):
        raise NotImplementedError

    def delete(self, kind, name):
        raise NotImplementedError

    def scale_zero(self, name):
        raise NotImplementedError

    def pods(self, name):
        raise NotImplementedError

    def revoke_keys(self, slot):
        """Revoke every inference key issued for the slot; raise if one cannot be revoked."""
        raise NotImplementedError


def result_path(root, slot):
    return Path(root) / 'inventory' / 'retirements' / (slot + '.json')


def read_result(root, slot):
    try:
        return read_json(result_path(root, slot), 8192)
    except (OSError, ValueError):
        return None


def write_result(root, slot, state, phase=None, error=None, request=None):
    path = result_path(root, slot)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = {'version': 1, 'slot': slot, 'state': state, 'observedAt': utc()}
    if phase:
        value['phase'] = phase
    if error:
        value['error'] = error
    if request:
        value['account'] = request['user']
        value['requestedAt'] = request['requestedAt']
    atomic_json(path, value)
    return value


def load_request(root, slot):
    try:
        value = read_json(Path(root) / 'policy' / 'retirements' / (slot + '.json'), 4096)
    except (OSError, ValueError):
        raise Refused('Retirement request is unreadable') from None
    if (not isinstance(value, dict) or value.get('slot') != slot or not isinstance(value.get('user'), str)
            or not ACCOUNT.fullmatch(value['user']) or not isinstance(value.get('requestedBy'), str)
            or not isinstance(value.get('requestedAt'), str) or len(value['requestedAt']) > 40):
        raise Refused('Retirement request is malformed')
    return value


def guard(root, config, slot, request):
    root = Path(root)
    if not SLOT.fullmatch(slot):
        raise Refused('Invalid slot')
    protected = config.get('protectedSlots', [])
    if not isinstance(protected, list) or slot in protected:
        raise Refused('Slot is protected')
    try:
        inventory = read_json(root / 'inventory' / 'inventory.json')
        assignments = read_json(root / 'policy' / 'assignments.json')
    except (OSError, ValueError):
        raise Refused('Capacity state is unreadable') from None
    record = inventory.get('slots', {}).get(slot)
    if not isinstance(record, dict) or record.get('state') not in ('ready', 'retiring'):
        raise Refused('Slot is not a ready provisioned slot')
    # The gateway lists the slots held by DELETED accounts; a live account's slot can never be wiped, whatever a request says.
    if slot not in assignments.get('assignedSlots', []) or slot not in assignments.get('deletedSlots', []):
        raise Refused('Slot is not held by a deleted account')


def set_inventory_state(root, slot, state):
    path = Path(root) / 'inventory' / 'inventory.json'
    inventory = read_json(path)
    inventory['slots'][slot]['state'] = state
    if state == 'retired':
        inventory['slots'][slot]['retiredAt'] = utc()
    atomic_json(path, inventory)


def unpublish(root, slot):
    path = Path(root) / 'inventory' / 'pool.json'
    pool = read_json(path)
    if slot in pool.get('slots', {}):
        del pool['slots'][slot]
        atomic_json(path, pool)


def stop_runtimes(ctx, slot, timeout=180):
    names = ctx.names(slot)
    for name in names['deployments']:
        if ctx.get('Deployment', name) is not None:
            ctx.scale_zero(name)
    deadline = ctx.monotonic() + timeout
    while True:
        if all(not [p for p in ctx.pods(name) if not p.get('metadata', {}).get('deletionTimestamp')]
               for name in names['deployments']):
            return
        if ctx.monotonic() > deadline:
            raise StepFailed('Runtime pods did not stop')
        ctx.sleep(3)


def delete_objects(ctx, slot, timeout=120):
    names = ctx.names(slot)
    order = [('Deployment', 'deployments'), ('Service', 'services'), ('PersistentVolumeClaim', 'claims'), ('Secret', 'secrets')]
    for kind, group in order:
        for name in names[group]:
            existing = ctx.get(kind, name)
            if existing is None:
                continue
            if existing.get('metadata', {}).get('labels', {}).get(OWNED_LABEL) != 'true':
                raise StepFailed('Object is not owned by the provisioner')
            ctx.delete(kind, name)
    deadline = ctx.monotonic() + timeout
    while True:
        remaining = [(kind, name) for kind, group in order for name in names[group] if ctx.get(kind, name) is not None]
        if not remaining:
            return
        if ctx.monotonic() > deadline:
            raise StepFailed('Objects remain after deletion')
        ctx.sleep(3)


def remove_tree(parent, name):
    """Delete parent/name without following links; refuse anything that is not a plain directory inside parent."""
    parent = Path(parent)
    if not re.fullmatch(r'[a-z0-9-]{1,40}', name):
        raise StepFailed('Unexpected directory name')
    if not parent.is_dir():
        return                      # nothing was ever stored here
    target = parent / name
    try:
        meta = os.lstat(target)
    except FileNotFoundError:
        return
    except OSError:
        raise StepFailed('Storage location is unavailable') from None
    if stat.S_ISLNK(meta.st_mode):
        os.unlink(target)          # a link is removed, never followed
        return
    if not stat.S_ISDIR(meta.st_mode):
        raise StepFailed('Unexpected storage object')
    try:
        for current, directories, files in os.walk(target, topdown=False, followlinks=False):
            for entry in files:
                os.unlink(os.path.join(current, entry))
            for entry in directories:
                path = os.path.join(current, entry)
                if os.path.islink(path):
                    os.unlink(path)
                else:
                    os.rmdir(path)
        os.rmdir(target)
    except OSError:
        raise StepFailed('Files could not be removed') from None
    if os.path.lexists(target):
        raise StepFailed('Files remain after removal')


def wipe_files(root, ctx, slot, service_ids):
    identity = identity_of(slot)
    private = Path(ctx.central) / 'dsh' / 'private'
    remove_tree(private, identity)
    for service_id in service_ids:
        if not re.fullmatch(r'[a-f0-9]{24}', service_id):
            raise StepFailed('Unexpected service identity')
        remove_tree(Path(ctx.services), service_id)
        remove_tree(Path(root) / 'inventory' / 'runtime-status', service_id)
    remove_tree(Path(root) / 'inventory' / 'runtime-tokens', identity)


def retire_slot(root, ctx, config, slot, service_ids):
    """Process one request end to end. Returns the result written."""
    root = Path(root)
    try:
        request = load_request(root, slot)
        guard(root, config, slot, request)
    except Refused as error:
        return write_result(root, slot, 'refused', error=str(error))
    phase = 'detach'
    try:
        write_result(root, slot, 'retiring', phase=phase, request=request)
        set_inventory_state(root, slot, 'retiring')     # first: the planner and the pool must not see it again
        unpublish(root, slot)
        phase = 'stop'
        write_result(root, slot, 'retiring', phase=phase, request=request)
        stop_runtimes(ctx, slot)
        phase = 'credentials'
        write_result(root, slot, 'retiring', phase=phase, request=request)
        try:
            ctx.revoke_keys(slot)
        except StepFailed:
            raise
        except Exception:
            raise StepFailed('Credentials could not be revoked') from None
        phase = 'objects'
        write_result(root, slot, 'retiring', phase=phase, request=request)
        delete_objects(ctx, slot)
        phase = 'files'
        write_result(root, slot, 'retiring', phase=phase, request=request)
        wipe_files(root, ctx, slot, service_ids)
        phase = 'finish'
        set_inventory_state(root, slot, 'retired')
        return write_result(root, slot, 'done', phase=phase, request=request)
    except StepFailed as error:
        return write_result(root, slot, 'quarantined', phase=phase, error=str(error), request=request)
    except Exception as error:     # unknown failure: never include its text
        return write_result(root, slot, 'quarantined', phase=phase, error='Unexpected ' + type(error).__name__, request=request)


def process_retirements(root, ctx, config, service_ids_for):
    """Handle every pending request. `service_ids_for(slot)` returns the slot's two service identities."""
    outcomes = {}
    try:
        entries = sorted(os.listdir(Path(root) / 'policy' / 'retirements'))
    except OSError:
        return outcomes
    for entry in entries:
        match = REQUEST.fullmatch(entry)
        if not match:
            continue
        slot = match.group(1)
        existing = read_result(root, slot)
        if existing and existing.get('state') in FINAL:
            continue
        outcomes[slot] = retire_slot(root, ctx, config, slot, service_ids_for(slot))
    return outcomes
