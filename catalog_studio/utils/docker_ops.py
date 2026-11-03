# utils/docker_ops.py
"""Wraps the docker cp / exec commands we've been running by hand tonight,
so the web app can shuttle mdf/ldf files in and out of the scratch
SQL Server container automatically."""

import subprocess

from config import (CONTAINER_NAME, CONTAINER_ATTACH_PATH, SCRATCH_SQL_IMAGE,
                    SQL_HOST_PORT, DB_CONFIG)


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def ensure_attach_dir():
    _run(["docker", "exec", CONTAINER_NAME, "mkdir", "-p", CONTAINER_ATTACH_PATH])
    _run([
        "docker", "exec", "-u", "root", CONTAINER_NAME,
        # owner only: the SQL Server 2019 image has no "mssql" group
        "chown", "mssql", CONTAINER_ATTACH_PATH,
    ])


def copy_into_container(host_path: str, container_filename: str):
    """Copy a file from the WSL host into the container's attach folder
    and fix ownership so the mssql service account can read/write it."""
    ensure_attach_dir()
    dest = f"{CONTAINER_NAME}:{CONTAINER_ATTACH_PATH}/{container_filename}"
    _run(["docker", "cp", host_path, dest])
    target = f"{CONTAINER_ATTACH_PATH}/{container_filename}"
    _run(["docker", "exec", "-u", "root", CONTAINER_NAME, "chown", "mssql", target])
    # docker cp keeps the host mode; a read-only copy attaches read-only.
    _run(["docker", "exec", "-u", "root", CONTAINER_NAME, "chmod", "660", target])


def copy_out_of_container(container_path: str, host_path: str):
    """Copy a file from an ABSOLUTE path inside the container back to the WSL
    host. Callers should get the real path from db.get_physical_files() rather
    than guessing a filename from the database name -- they don't always match."""
    src = f"{CONTAINER_NAME}:{container_path}"
    _run(["docker", "cp", src, host_path])


def remove_in_container(container_path: str):
    """Delete a server-side file (e.g. a .bak already copied to the host)."""
    _run(["docker", "exec", CONTAINER_NAME, "rm", "-f", container_path])


def container_exists() -> bool:
    try:
        _run(["docker", "inspect", "-f", "{{.Id}}", CONTAINER_NAME])
        return True
    except RuntimeError:
        return False


def container_image() -> str:
    try:
        return _run(["docker", "inspect", "-f", "{{.Config.Image}}", CONTAINER_NAME]).strip()
    except RuntimeError:
        return ""


def run_command():
    """The one docker run that makes the app's own SQL Server 2019 container.
    Bound to 127.0.0.1 so it is never reachable from the network."""
    return [
        "docker", "run", "-d", "--name", CONTAINER_NAME, "--restart", "unless-stopped",
        "-e", "ACCEPT_EULA=Y", "-e", f"MSSQL_SA_PASSWORD={DB_CONFIG['password']}",
        "-p", f"127.0.0.1:{SQL_HOST_PORT}:1433", SCRATCH_SQL_IMAGE,
    ]


def ensure_container() -> str:
    """Start the app's SQL Server 2019 container, creating it the first time.

    Only ever touches CONTAINER_NAME. Returns what it did: "running",
    "started" or "created". The first create pulls the image (a few minutes).
    Refuses to reuse a container of that name built from another image.
    """
    if container_exists():
        image = container_image()
        if image and image != SCRATCH_SQL_IMAGE:
            raise RuntimeError(
                f"Container '{CONTAINER_NAME}' exists but runs {image}, not {SCRATCH_SQL_IMAGE}. "
                f"Remove or rename it; Catalog Studio will not change it.")
        if container_is_running():
            return "running"
        _run(["docker", "start", CONTAINER_NAME])
        return "started"
    _run(run_command())
    return "created"


def container_is_running() -> bool:
    try:
        out = _run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME])
        return out.strip() == "true"
    except RuntimeError:
        return False
