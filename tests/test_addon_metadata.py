# coding=utf-8
"""
addon.xml - the install contract.

Nothing in the addon reads most of this file; Kodi does, at install time, and
the self-updater scrapes it off GitHub. A mistake here is only visible as
"Kodi refuses to install the zip" or "the update check stopped finding
versions", neither of which any other test would catch.
"""

from __future__ import absolute_import

import os
import re
import xml.etree.ElementTree as ET

from lib.updater import NEWS_RE, VERSION_RE
from lib.version import Version

from .base import KodiTestCase
from . import REPO_ROOT

ADDON_XML = os.path.join(REPO_ROOT, "addon.xml")

# Kodi's own addon id rules: lowercase, dot-separated, no spaces.
ADDON_ID_RE = re.compile(r"^[a-z][a-z0-9.]*[a-z0-9]$")


def addon_xml_text():
    with open(ADDON_XML, "r", encoding="utf-8") as fp:
        return fp.read()


class AddonMetadataTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        self.text = addon_xml_text()
        self.root = ET.fromstring(self.text)

    def test_the_addon_id_is_the_one_everything_else_assumes(self):
        """
        The id is the directory name Kodi installs into and the profile path
        the addon writes settings to; renaming it orphans every existing
        install's data.
        """
        self.assertEqual(self.root.get("id"), "script.plexmod")
        self.assertTrue(ADDON_ID_RE.match(self.root.get("id")))
        self.assertTrue(self.root.get("name"))
        self.assertTrue(self.root.get("provider-name"))

    def test_the_version_is_a_version(self):
        version = self.root.get("version")
        self.assertTrue(version)
        # Parses under the same rules the updater compares with.
        self.assertEqual(str(Version(version)), version)

    def test_the_updater_can_read_this_file(self):
        """
        The self-update check pulls addon.xml raw off GitHub and regexes it.
        Reordering the header past <requires> silently ends update checks.
        """
        self.assertEqual(VERSION_RE.findall(self.text), [self.root.get("version")])
        news = NEWS_RE.findall(self.text)
        self.assertTrue(news, "no <news> block - the update prompt would be blank")
        self.assertTrue(news[0].strip())

    def test_every_entry_point_exists(self):
        libraries = [ext.get("library") for ext in self.root.findall("extension")
                     if ext.get("library")]
        self.assertTrue(libraries)
        for library in libraries:
            self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, library)), library)

    def test_every_declared_asset_ships(self):
        assets = self.root.find("./extension/assets")
        self.assertIsNotNone(assets, "no <assets>: Kodi shows the addon with no icon")
        for asset in assets:
            self.assertTrue(asset.text)
            self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, asset.text)), asset.text)

    def test_every_dependency_is_pinned(self):
        requires = self.root.findall("./requires/import")
        self.assertTrue(requires)
        for imp in requires:
            self.assertTrue(imp.get("addon"))
            self.assertTrue(imp.get("version"), "{0} has no version".format(imp.get("addon")))
        python = [imp for imp in requires if imp.get("addon") == "xbmc.python"]
        self.assertEqual(len(python), 1, "exactly one xbmc.python dependency is required")

    def test_the_english_metadata_kodi_shows_is_present(self):
        metadata = self.root.find("./extension[@point='xbmc.addon.metadata']")
        self.assertIsNotNone(metadata)
        for tag in ("summary", "description", "disclaimer", "license"):
            self.assertTrue(metadata.findall(tag), "no <{0}>".format(tag))

    def test_the_stub_addon_info_matches_the_working_tree(self):
        """
        The harness reads the real addon.xml rather than hardcoding, so a
        version bump does not need a test change - guard that wiring.
        """
        import xbmcaddon
        addon = xbmcaddon.Addon()
        self.assertEqual(addon.getAddonInfo("version"), self.root.get("version"))
        self.assertEqual(addon.getAddonInfo("id"), self.root.get("id"))
