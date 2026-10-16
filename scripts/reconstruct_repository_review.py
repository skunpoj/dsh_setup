"""Reconstruct the exact review prompt from pinned Git objects and specification.

Writes local files only. Does not submit inference or change any deployment.
"""
import argparse
import hashlib
import json
from pathlib import Path

from prepare_repository_accuracy_test import git, redact, render_sources


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--specification', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--dsh-repo', type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument('--gpu-repo', type=Path, default=Path(__file__).resolve().parents[2]/'GPU_server')
    a = ap.parse_args(); spec = json.loads(a.specification.read_text(encoding='utf-8'))
    repos = {'DSH': a.dsh_repo, 'GPU': a.gpu_repo}; blocks = []
    for entry in spec['selectedSources']:
        text = redact(git(repos[entry['repo']], 'show', entry['revision']+':'+entry['path']).decode('utf-8'))
        if hashlib.sha256(text.encode()).hexdigest() != entry['sha256']:
            raise ValueError('Frozen source mismatch: '+entry['id'])
        blocks.append({**entry, 'content': text})
    prompt = render_sources(blocks, spec['instructions'], spec['questionsJSON'], spec.get('promptPrefix', ''))
    if hashlib.sha256(prompt.encode()).hexdigest() != spec['promptSHA256']:
        raise ValueError('Reconstructed prompt hash mismatch')
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output/'prompt.txt').write_text(prompt, encoding='utf-8')
    (a.output/'selected-sources.json').write_text(json.dumps(blocks), encoding='utf-8')
    print(json.dumps({'sources': len(blocks), 'promptSHA256': spec['promptSHA256']}))


if __name__ == '__main__': main()
