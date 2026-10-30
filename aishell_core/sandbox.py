"""Linux plugin-tool sandbox: no host workspace/home mounts or host network."""
from pathlib import Path
import shutil
import sys


def sandbox_command(command, script):
    bwrap = shutil.which("bwrap") if sys.platform == "linux" else None
    if not bwrap:
        raise RuntimeError("Plugin execution requires Linux bubblewrap; no unsandboxed fallback is allowed.")
    args = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
    for path in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(path).exists():
            args.extend(["--ro-bind", path, path])
    # A virtual environment is runtime code, not a project/home mount.
    for prefix in sorted({sys.prefix, sys.base_prefix}):
        runtime = Path(prefix).resolve()
        if not runtime.is_relative_to("/usr"):
            if runtime in {Path("/"), Path.home().resolve(), Path.cwd().resolve()}:
                raise RuntimeError("Refusing an interpreter runtime that would expose a host workspace.")
            args.extend(["--ro-bind", str(runtime), str(runtime)])
    target = "/input/script" + Path(script).suffix
    args.extend(["--ro-bind", str(script), target, "--proc", "/proc", "--dev", "/dev",
                 "--tmpfs", "/tmp", "--tmpfs", "/work", "--chdir", "/work",
                 "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/work",
                 "--setenv", "LANG", "C.UTF-8", "--"])
    args.extend([target if arg == str(script) else arg for arg in command])
    return args


def limit_resources():
    """Applied in the Linux child before bubblewrap; output cannot fill the host disk."""
    import resource
    for name, value in ((resource.RLIMIT_FSIZE, 1048576), (resource.RLIMIT_CPU, 10),
                        (resource.RLIMIT_AS, 536870912), (resource.RLIMIT_NOFILE, 64),
                        (resource.RLIMIT_CORE, 0)):
        resource.setrlimit(name, (value, value))
