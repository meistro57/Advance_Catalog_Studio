# utils/docker_ops.py
"""Wraps the docker cp / exec commands we've been running by hand tonight,
so the web app can shuttle mdf/ldf files in and out of the scratch
SQL Server container automatically."""

import subprocess

from config import CONTAINER_NAME, CONTAINER_ATTACH_PATH


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def ensure_attach_dir():
    _run(["docker", "exec", CONTAINER_NAME, "mkdir", "-p", CONTAINER_ATTACH_PATH])
    _run([
        "docker", "exec", "-u", "root", CONTAINER_NAME,
        "chown", "mssql:mssql", CONTAINER_ATTACH_PATH,
    ])


def copy_into_container(host_path: str, container_filename: str):
    """Copy a file from the WSL host into the container's attach folder
    and fix ownership so the mssql service account can read/write it."""
    ensure_attach_dir()
    dest = f"{CONTAINER_NAME}:{CONTAINER_ATTACH_PATH}/{container_filename}"
    _run(["docker", "cp", host_path, dest])
    _run([
        "docker", "exec", "-u", "root", CONTAINER_NAME,
        "chown", "mssql:mssql", f"{CONTAINER_ATTACH_PATH}/{container_filename}",
    ])


def copy_out_of_container(container_path: str, host_path: str):
    """Copy a file from an ABSOLUTE path inside the container back to the WSL
    host. Callers should get the real path from db.get_physical_files() rather
    than guessing a filename from the database name -- they don't always match."""
    src = f"{CONTAINER_NAME}:{container_path}"
    _run(["docker", "cp", src, host_path])


def container_is_running() -> bool:
    try:
        out = _run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME])
        return out.strip() == "true"
    except RuntimeError:
        return False
