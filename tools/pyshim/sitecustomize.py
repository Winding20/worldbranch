# -*- coding: utf-8 -*-
"""Sandbox compatibility shim for Windows Python tooling.

Loaded automatically via PYTHONPATH + sitecustomize.

Why this exists
---------------
Inside the DSH sandbox, a directory created with a restrictive mode
(``os.mkdir(path, 0o700)``, which is exactly what ``tempfile.mkdtemp`` does)
ends up with an inheritance that denies the process write access to it.
Every later write into that directory fails with ``PermissionError``.

That single behaviour breaks ``pip`` (its unpack/build temp dirs),
``pytest`` (``tmp_path``), ``venv``, and most installers, even though ordinary
``os.makedirs(path)`` / ``os.mkdir(path)`` directories work fine.

What this shim does
-------------------
On Windows the ``mode`` argument of ``os.mkdir`` carries no real meaning
(NTFS uses ACLs, inherited from the parent). So we drop the restrictive mode
and let the new directory inherit normal permissions, which is what stock
CPython effectively does for the default ``0o777`` path.

``os.chmod`` on a directory is likewise reduced to a no-op, because
``tempfile`` uses ``chmod(0o700)`` while cleaning up and that call fails here
for the same reason.

Nothing else is patched. If DSH is ever run with full access, or on a machine
where the sandbox does not behave this way, the shim is harmless: dropping the
mode argument of ``mkdir`` is exactly the documented Windows behaviour.
"""

import os
import stat
import sys

if sys.platform == "win32" and not getattr(os, "_dsh_sandbox_shim", False):
    _real_mkdir = os.mkdir
    _real_chmod = os.chmod

    def _mkdir(path, mode=0o777, *, dir_fd=None):
        # Never forward a restrictive mode: let the directory inherit.
        if dir_fd is None:
            return _real_mkdir(path, 0o777)
        return _real_mkdir(path, 0o777, dir_fd=dir_fd)

    def _chmod(path, mode, *, dir_fd=None, follow_symlinks=True):
        try:
            is_dir = stat.S_ISDIR(os.stat(path).st_mode)
        except OSError:
            is_dir = False
        if is_dir:
            # Directory permissions are ACL-based on Windows; mode is a no-op.
            return None
        return _real_chmod(path, mode, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    os.mkdir = _mkdir
    os.chmod = _chmod
    os._dsh_sandbox_shim = True