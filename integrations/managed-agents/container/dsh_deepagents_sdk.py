"""Python SDK entry: managed model, bounded per-user workspace, explicit write approval."""
from pathlib import Path
from dsh_agent_model import DSHManagedChat

def create_dsh_agent(project, *, checkpointer):
 from deepagents import create_deep_agent
 from deepagents.backends import FilesystemBackend
 root=Path(project).resolve(strict=True)
 if not root.is_dir() or not root.is_relative_to(Path('/workspace').resolve()): raise ValueError('A private /workspace project is required')
 if checkpointer is None: raise ValueError('An explicit private per-user checkpointer is required')
 return create_deep_agent(model=DSHManagedChat(),backend=FilesystemBackend(root_dir=str(root),virtual_mode=True),checkpointer=checkpointer,interrupt_on={'write_file':True,'edit_file':True,'execute':True})
