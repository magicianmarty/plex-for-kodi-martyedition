# coding=utf-8
"""
Running on the Pythons Kodi ships.

Kodi 19/20 run Python 3.8, Kodi 21 runs 3.11 and Kodi 22 (Piers) runs 3.14, so
the add-on has to keep importing across six years of stdlib removals - on the
oldest and the newest at once, from one branch.

These are source-level checks, in the same spirit as test_vfs_handles.py. What
they guard against is an ImportError while Kodi is starting the add-on, which no
runtime test in this suite would ever reach: nothing here imports the vendored
HTTP cache or the ISO-639 tables, so reverting the whole Python 3.14 port leaves
the suite green.
"""

from __future__ import absolute_import

import ast
import os
import sys
import sysconfig

from .base import KodiTestCase
from . import REPO_ROOT

LIB = os.path.join(REPO_ROOT, "lib")
VENDORED = os.path.join(LIB, "_included_packages")

# Gone from the standard library, with the release that dropped them. Importing
# one of these unguarded is an add-on that does not start on that Kodi.
REMOVED_MODULES = {
    # 3.12
    "asynchat": "3.12", "asyncore": "3.12", "distutils": "3.12", "imp": "3.12",
    "smtpd": "3.12",
    # 3.13, PEP 594
    "aifc": "3.13", "audioop": "3.13", "cgi": "3.13", "cgitb": "3.13",
    "chunk": "3.13", "crypt": "3.13", "imghdr": "3.13", "lib2to3": "3.13",
    "mailcap": "3.13", "msilib": "3.13", "nis": "3.13", "nntplib": "3.13",
    "ossaudiodev": "3.13", "pipes": "3.13", "sndhdr": "3.13", "spwd": "3.13",
    "sunau": "3.13", "telnetlib": "3.13", "uu": "3.13", "xdrlib": "3.13",
    # Not stdlib at all: it arrives with setuptools, which a Kodi Python is not
    # required to have and 3.12+ no longer seeds into virtual environments.
    "pkg_resources": "setuptools",
}


def python_files(root):
    for base, _, files in os.walk(root):
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(base, name)


def parse(path):
    with open(path, "r", encoding="utf-8") as fp:
        return ast.parse(fp.read(), filename=path)


def guarded_nodes(tree):
    """
    Every import node sitting under a try/except that catches ImportError.

    Both halves count: the attempt in the body and the fallback in the handler
    are each conditional on the other one's outcome, which is the whole point of
    the idiom.
    """
    guarded = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches_import_error = False
        for handler in node.handlers:
            names = []
            if handler.type is None:
                catches_import_error = True
            elif isinstance(handler.type, ast.Name):
                names = [handler.type.id]
            elif isinstance(handler.type, ast.Tuple):
                names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
            if any(n in ("ImportError", "ModuleNotFoundError", "Exception") for n in names):
                catches_import_error = True
        if catches_import_error:
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    guarded.add(child)
    return guarded


def imported_roots(node):
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if node.level:  # relative import, never the stdlib
        return []
    return [(node.module or "").split(".")[0]]


def stdlib_module_names():
    names = set(sys.builtin_module_names)
    names |= set(getattr(sys, "stdlib_module_names", ()))  # 3.10+
    # Directory scan so this still says something on 3.8/3.9.
    stdlib = sysconfig.get_paths().get("stdlib")
    if stdlib and os.path.isdir(stdlib):
        for entry in os.listdir(stdlib):
            if entry.endswith(".py"):
                names.add(entry[:-3])
            elif os.path.isdir(os.path.join(stdlib, entry)) and entry != "site-packages":
                names.add(entry)
    return names


class VendoredPackagesTest(KodiTestCase):
    def test_nothing_vendored_shadows_the_standard_library(self):
        """
        lib/_included_packages/__init__.py does sys.path.insert(0, ...), so a
        vendored top-level name that also exists in the stdlib wins for every
        later import in the whole Kodi process, not just ours.

        The vendored `typing.py` was a Python 2 backport that cannot import on
        Python 3 at all; it survived for years only because `typing` was already
        in sys.modules by the time the path was inserted.
        """
        stdlib = stdlib_module_names()
        collisions = []
        for entry in sorted(os.listdir(VENDORED)):
            name = entry[:-3] if entry.endswith(".py") else entry
            if name.startswith("_") or name == "__pycache__":
                continue
            if not (entry.endswith(".py") or os.path.isdir(os.path.join(VENDORED, entry))):
                continue
            if name in stdlib:
                collisions.append(name)
        self.assertEqual([], collisions,
                         "vendored copies shadow the stdlib for the whole process")

    def test_typing_comes_from_the_standard_library(self):
        import typing
        self.assertNotIn("_included_packages", os.path.abspath(typing.__file__))


class RemovedStdlibTest(KodiTestCase):
    def test_no_unguarded_import_of_a_module_that_no_longer_exists(self):
        offenders = []
        for path in python_files(LIB):
            tree = parse(path)
            guarded = guarded_nodes(tree)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)) or node in guarded:
                    continue
                for root in imported_roots(node):
                    if root in REMOVED_MODULES:
                        offenders.append("{0}:{1}: {2} (gone in {3})".format(
                            os.path.relpath(path, REPO_ROOT), node.lineno, root,
                            REMOVED_MODULES[root]))
        self.assertEqual([], offenders,
                         "import these behind try/except ImportError, with a fallback")

    def test_the_guard_detection_is_not_vacuous(self):
        guarded = parse_source("""
try:
    from html import escape
except ImportError:
    from cgi import escape
""")
        self.assertEqual([], unguarded_removed(guarded))

        bare = parse_source("import telnetlib\n")
        self.assertEqual(["telnetlib"], unguarded_removed(bare))


class DeprecatedApiTest(KodiTestCase):
    def test_nothing_calls_datetime_utcnow(self):
        """
        utcnow() returns a naive datetime that claims to be local time, and 3.12
        deprecated it for removal - on 3.14 every call warns. The vendored HTTP
        cache stores and compares those timestamps, so the replacement has to
        stay naive (`.replace(tzinfo=None)`) or existing on-disk caches read as
        expired.
        """
        offenders = []
        for path in python_files(LIB):
            with open(path, "r", encoding="utf-8") as fp:
                for lineno, line in enumerate(fp, 1):
                    if "utcnow(" in line:
                        offenders.append("{0}:{1}".format(
                            os.path.relpath(path, REPO_ROOT), lineno))
        self.assertEqual([], offenders, "use datetime.now(timezone.utc) instead")


def parse_source(source):
    return ast.parse(source)


def unguarded_removed(tree):
    guarded = guarded_nodes(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node not in guarded:
            found.extend(r for r in imported_roots(node) if r in REMOVED_MODULES)
    return found
