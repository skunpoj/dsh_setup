"""Bake the reviewed private workspace tools into a new image, never a live user."""
from pathlib import Path
from configure_platform_guide import write_atomic
from workspace_tools_overlay import CORE, patch_resolver


def install(core=Path(CORE)):
    # Validate both package variants before touching either installed file.
    changes = {core/name:patch_resolver((core/name).read_bytes(),name)
               for name in ['TurnResourceResolver.js','TurnResourceResolver.mjs']}
    for file, data in changes.items():
        write_atomic(file,data.decode('utf-8'),0o644)


if __name__ == '__main__':
    install()
