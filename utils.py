import os
import subprocess
import shlex
import posixpath


def run_cmd(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, encoding="utf-8", errors="ignore", shell=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def list_adb_devices():
    code, out, _ = run_cmd(["adb", "devices"])
    if code != 0:
        return []
    lines = out.splitlines()[1:]
    res = []
    for l in lines:
        l = l.strip()
        if not l:
            continue
        parts = l.split()
        if len(parts) >= 2 and parts[1] == "device":
            res.append(parts[0])
    return res


def adb_list_dir(serial, path):
    if not serial:
        return []
    cmd = [
        "adb",
        "-s",
        serial,
        "shell",
        f"cd {shlex.quote(path)} && for f in .* *; do [ \"$f\" = '.' ] || [ \"$f\" = '..' ] || if [ -d \"$f\" ]; then printf '%s/\\n' \"$f\"; else printf '%s\\n' \"$f\"; fi; done",
    ]
    code, out, _ = run_cmd(cmd, timeout=20)
    if code != 0 and not out:
        return []
    items = []
    for line in out.splitlines():
        name = line.strip()
        if not name:
            continue
        if name in ("*", ".*"):
            continue
        is_dir = name.endswith("/")
        clean = name[:-1] if is_dir else name
        if clean in [".", ".."]:
            continue
        items.append({"name": clean, "is_dir": is_dir})
    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return items


def adb_path_exists_dir(serial, path):
    if not serial:
        return False
    code, out, _ = run_cmd(["adb", "-s", serial, "shell", "test", "-d", path, "&&", "echo", "1", "||", "echo", "0"])
    if code != 0:
        return False
    return out.strip().endswith("1")


def ensure_remote_dir(serial, path):
    if not serial:
        return False
    code, _, _ = run_cmd(["adb", "-s", serial, "shell", "mkdir", "-p", path])
    return code == 0


def remote_find_files(serial, root):
    if not serial:
        return []
    cmd = ["adb", "-s", serial, "shell", f"cd {shlex.quote(root)} && find . -type f -print || true"]
    code, out, _ = run_cmd(cmd, timeout=60)
    if code != 0 and not out:
        return []
    files = []
    for line in out.splitlines():
        p = line.strip()
        if not p or p in ["."]:
            continue
        if p.startswith("./"):
            p = p[2:]
        files.append(p)
    return files
