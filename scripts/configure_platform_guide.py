"""Install one versioned platform guide without replacing private user context.

The image stage owns the Claude/Kilo policy and the pinned TrueForge adapter.
The runtime stage refreshes only a bounded managed block in DSH's AGENTS files.
"""
import argparse
import hashlib
import json
from pathlib import Path

BEGIN = '<!-- DSH:SHARED-PLATFORM-GUIDE:BEGIN -->'
END = '<!-- DSH:SHARED-PLATFORM-GUIDE:END -->'
GUIDE = Path('/opt/dsh/container/PLATFORM_GUIDE.md')
CORE = Path('/usr/local/lib/node_modules/@truefoundry/trueforge/node_modules/@truefoundry/trueforge-core/dist/agent-session')
HASHES = {
    'TurnResourceResolver.mjs': '7b33cbe4715b945d3df82379f85367dd590d324a89a8a3482fd5f7a0f7d9b0c2',
    'TurnResourceResolver.js': '7e8ea835620b58a40c782b64204f2a8f82aa47e39ed8cc5dffd3a78d40cdd069',
}
TARGET = 'instruction: agentInfo ? void 0 : spec.instructions,'
PATCHED = 'instruction: dshPlatformInstructions(agentInfo ? undefined : spec.instructions),'


def managed_content(existing, guide):
    """Unknown/unbalanced markers refuse mutation; outside text stays exact."""
    if existing.count(BEGIN) != existing.count(END) or existing.count(BEGIN) > 1:
        raise ValueError('Ambiguous shared guide markers')
    block = BEGIN + '\n' + guide.rstrip() + '\n' + END
    if BEGIN in existing:
        before, rest = existing.split(BEGIN)
        _, after = rest.split(END)
        return before + block + after
    return existing + ('\n\n' if existing else '') + block + '\n'


def write_atomic(file, content, mode=0o600):
    if file.is_symlink():
        raise ValueError('Refusing instruction-file symlink')
    if file.exists() and file.read_text(encoding='utf-8') == content:
        return
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(file.name + '.platform-guide-new')
    # Exclusive creation also refuses a stale or attacker-created staging path.
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(content)
    temporary.chmod(mode)
    temporary.replace(file)


def trueforge_patch(raw, filename):
    source = raw.decode('utf-8')
    if PATCHED in source:
        # Idempotency still verifies the rest of the original package bytes.
        original = source.replace(PATCHED, TARGET)
        prefix = ("import {dshPlatformInstructions} from '/opt/dsh/container/platform_guide.mjs';\n"
                  if filename.endswith('.mjs') else
                  "const {dshPlatformInstructions} = require('/opt/dsh/container/platform_guide.cjs');\n")
        if not original.startswith(prefix):
            raise ValueError('Unexpected TrueForge guide adapter')
        original = original[len(prefix):].encode('utf-8')
        if hashlib.sha256(original).hexdigest() != HASHES[filename]:
            raise ValueError('Modified TrueForge adapter source')
        return raw
    if hashlib.sha256(raw).hexdigest() != HASHES[filename] or source.count(TARGET) != 1:
        raise ValueError('Unreviewed TrueForge instruction boundary')
    prefix = ("import {dshPlatformInstructions} from '/opt/dsh/container/platform_guide.mjs';\n"
              if filename.endswith('.mjs') else
              "const {dshPlatformInstructions} = require('/opt/dsh/container/platform_guide.cjs');\n")
    return (prefix + source.replace(TARGET, PATCHED)).encode('utf-8')


def install_image(guide_path=GUIDE, core=CORE, etc=Path('/etc')):
    guide = guide_path.read_text(encoding='utf-8')
    # Validate all patch targets before changing either one.
    patched = {core / name: trueforge_patch((core / name).read_bytes(), name) for name in HASHES}
    for file, raw in patched.items():
        write_atomic(file, raw.decode('utf-8'), 0o644)
    claude = etc / 'claude-code/CLAUDE.md'
    write_atomic(claude, managed_content(claude.read_text(encoding='utf-8') if claude.exists() else '', guide), 0o644)
    kilo = etc / 'kilo/kilo.json'
    policy = json.loads(kilo.read_text(encoding='utf-8'))
    policy['instructions'] = list(dict.fromkeys([str(guide_path), *policy.get('instructions', [])]))
    write_atomic(kilo, json.dumps(policy, indent=2) + '\n', 0o644)


def install_runtime(state, workspace, guide_path=GUIDE):
    guide = guide_path.read_text(encoding='utf-8')
    for file in [state / 'AGENTS.md', workspace / 'AGENTS.md']:
        existing = file.read_text(encoding='utf-8') if file.exists() else ''
        # A newer block explicitly supersedes the old generated gateway hints;
        # retain the old text and all user edits rather than guessing ownership.
        current = 'Platform routing and limits below supersede earlier generated gateway examples.\n\n' + guide
        if file.exists() and BEGIN not in existing:
            backup = file.with_name(file.name + '.before-shared-guide-' + hashlib.sha256(existing.encode()).hexdigest()[:12])
            if not backup.exists():
                write_atomic(backup, existing)
        write_atomic(file, managed_content(existing, current))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', action='store_true')
    parser.add_argument('--state', type=Path)
    parser.add_argument('--workspace', type=Path, default=Path('/workspace'))
    args = parser.parse_args()
    if args.image:
        install_image()
    if args.state:
        install_runtime(args.state, args.workspace)
    if not args.image and not args.state:
        parser.error('Choose --image or --state')
    print(json.dumps({'guideSHA256': hashlib.sha256(GUIDE.read_bytes()).hexdigest(),
                      'imagePoliciesInstalled': args.image, 'runtimeInstructionsInstalled': bool(args.state)}))


if __name__ == '__main__':
    main()
