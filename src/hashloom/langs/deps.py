"""The dependency-set component of a toolchain identity.

Each adapter appends ` deps <file>=<digest12>` to its version core when the
project commits a dependency source (a lockfile, or a declared manifest as
the fallback grain) at its root — so a green from an environment with a
different declared dependency set is never trusted, while a project with no
dependency source keeps the version-only identity and no key ever moves for
it. The digest is content-addressed over CRLF-normalised bytes: git autocrlf
is the one cosmetic difference that correlates with OS, and normalising it
keeps the shipped CI(Linux)-serves-Mac/Windows promise for matching
checkouts. OS/arch stay out of the identity deliberately (see
docs/hosted-store.md item 3); installed-env drift belongs to revocation.

The digest is memoised per path, validated by (mtime_ns, size) — acceptable
for key material where verify's impl_hash stays always-fresh, because
lockfiles change via package-manager runs, not the sub-mtime-tick regenerate
loops the -B rationale in verify.py guards against; the residual
same-size-same-tick caveat is the grain cached_impl_hash already accepts.
Stat values are taken before the read, so a write racing the read self-heals
on the next call.
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

# path -> (st_mtime_ns, st_size, digest12); keyed by path so the memo stays
# bounded across lockfile edits in a long-lived serve
_cache: dict[str, tuple[int, int, str]] = {}


def dep_suffix(root: Path, candidates: tuple[str, ...]) -> str:
    """`" deps <file>=<digest12>"` for the first readable candidate, else "".

    Never raises: an unreadable or vanished file degrades to the next
    candidate (ultimately to the version-only identity), never to a
    bad_toolchain — that error class is reserved for real toolchain failures.
    """
    for name in candidates:
        path = root / name
        try:
            st = path.stat()
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        cached = _cache.get(str(path))
        if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
            return f" deps {name}={cached[2]}"
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()[:12]
        _cache[str(path)] = (st.st_mtime_ns, st.st_size, digest)
        return f" deps {name}={digest}"
    return ""
