"""Create inert review artifacts; never apply patches or invoke Git."""
import difflib
import os
from pathlib import Path
from uuid import uuid4


def propose_patch(source, replacement, directory):
    source = Path(source)
    # Restrict patch headers to an explicit relative source path.
    if source.is_absolute() or '..' in source.parts or not source.parts or any(c in str(source) for c in '\n\r\t\\'):
        raise ValueError("Patch target must be a plain workspace-relative file path")
    if source.is_symlink() or not source.resolve().is_relative_to(Path.cwd().resolve()):
        raise ValueError("Patch target must stay inside the workspace")
    if source.stat().st_size > 1048576 or len(replacement.encode()) > 1048576:
        raise ValueError("Patch source and replacement must be at most 1 MiB")
    original = source.read_text(encoding="utf-8")
    # Avoid malformed unified diffs for unterminated final lines.
    def lines(value):
        return value.splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines(original), lines(replacement), fromfile="a/" + source.as_posix(), tofile="b/" + source.as_posix()))
    if not diff:
        raise ValueError("No changes to propose")
    patch = ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n' for line in diff)
    directory = Path(directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / (uuid4().hex + '.patch')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(patch)
    return target
