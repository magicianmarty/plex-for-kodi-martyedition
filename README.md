# Plex for Kodi — Marty Edition

[![tests](https://github.com/magicianmarty/plex-for-kodi-martyedition/actions/workflows/tests.yml/badge.svg)](https://github.com/magicianmarty/plex-for-kodi-martyedition/actions/workflows/tests.yml)
[![package](https://github.com/magicianmarty/plex-for-kodi-martyedition/actions/workflows/package.yml/badge.svg)](https://github.com/magicianmarty/plex-for-kodi-martyedition/actions/workflows/package.yml)
[![Kodi 19–22](https://img.shields.io/badge/Kodi-19%20%7C%2020%20%7C%2021%20%7C%2022-blue)](https://kodi.tv)
[![License: GPL-2.0-only](https://img.shields.io/badge/license-GPL--2.0--only-lightgrey)](LICENSE.txt)

A Plex client for Kodi, tuned for people who actually live in their library:
quality-of-life changes for power content users, on top of the excellent
PlexMod for Kodi.

Maintained by [**magicianmarty**](https://github.com/magicianmarty).

## This is a separate project

It builds on [**pannal's PM4K / PlexMod for Kodi**](https://github.com/pannal/plex-for-kodi)
(branch `develop_kodi21`), which is itself a fork of Plex Inc.'s official
[plex-for-kodi](https://github.com/plexinc/plex-for-kodi). Effectively all of
the client you are running was written by them; this repository is a set of
changes on top, maintained separately and released on its own schedule.

**It is not affiliated with, endorsed by, or supported by Plex Inc. or pannal.**
Nothing here has been through their review. So:

- Problems with **this build** → [open an issue here](https://github.com/magicianmarty/plex-for-kodi-martyedition/issues).
- Do **not** report them on the Plex forums thread or on pannal's tracker — this
  is not their code, and working that out costs them time.
- Fixes that are not specific to this edition get offered back upstream, where
  everyone benefits.

## What it is for

Upstream is built to be a good general-purpose Plex client. This edition assumes
something narrower: a large, deliberately curated library, a display chain worth
feeding, and someone who knows what they want to watch and in what quality. The
changes follow from that.

**Rules it sticks to:**

1. **A press, not a menu dive.** Anything you do on every visit belongs on the
   screen, not four levels into a dropdown.
2. **No regressions for anyone else.** Changes are additive or they are fixes;
   where it is a matter of taste, upstream's behaviour stays the default.
3. **Format-aware.** Dolby Vision, Atmos, HDR and 4K are what people with good
   gear sort by. They get first-class treatment.
4. **Fix the bug, don't route around it.** Crashes get fixed at the cause and
   covered by a test, not defended against at the call site.
5. **Prove it.** Behaviour that can be tested outside Kodi is tested outside
   Kodi, and CI runs the suite on every Python version Kodi ships — 3.8
   through 3.14, from one branch.

## What's different so far

| Change | What it gets you |
|---|---|
| **One-click quick-filter chips** | An always-visible chip bar on the library views: Dolby Vision, Dolby Atmos, HDR, 4K, Unplayed. One press each way instead of a three-to-five click dive through the filter dropdown. The chips drive the existing filter plumbing, so they persist per section and stack with each other; 4K drives the resolution filter. Video sections only. |
| **Filters named like the format** | The dropdown says "Dolby Vision" rather than `DOVI`, and gained a "Dolby Atmos" entry — the server advertises that filter, upstream just had no label for it. |
| **Seek OSD crash fix** | `updateProgress()` divided by an offset that is `None` until the first playback tick lands, which killed the seek OSD for the rest of the session with a `TypeError`. Now guarded the way `trueOffset()` already was. |
| **Kodi 22 (Piers) support** | Kodi 22 ships Python 3.14, which drops modules the add-on's vendored packages still reached for. The vendored Python 2 `typing` backport is gone (it sat ahead of the stdlib on `sys.path`), `datetime.utcnow()` is replaced without changing what existing caches compare against, and `pkg_resources` is now optional. `addon.xml` needs nothing: Kodi 22 offers `xbmc.python` 3.1.0, a minor bump over the 3.0.0 we require. |
| **Tests and CI** | The suite runs on every push and pull request across Python 3.8 (Kodi 19/20), 3.11 (Kodi 21) and 3.14 (Kodi 22) plus Windows, the add-on is byte-compiled against Kodi 19's Python, and an installable zip is built and checked on every run. |

## Install

This edition is **not** in any Kodi repository — install the zip by hand.

1. Get a zip:
   - a tagged build from [Releases](https://github.com/magicianmarty/plex-for-kodi-martyedition/releases), or
   - the `script.plexmod-<version>` artifact from the latest green
     [package run](https://github.com/magicianmarty/plex-for-kodi-martyedition/actions/workflows/package.yml)
     if you want current `main`.
2. In Kodi: **Settings → Add-ons → Install from zip file**, and pick it.
3. Launch **Plex** from Programs / Video add-ons.

Building one yourself is exactly what CI does:

```sh
git archive --format=zip --prefix=script.plexmod/ -o script.plexmod.zip HEAD
```

The folder inside the zip has to be named `script.plexmod`; that is the add-on
id Kodi installs under.

### Two things worth knowing

**It replaces an existing PM4K install.** This edition keeps the `script.plexmod`
add-on id, so Kodi treats it as the same add-on: installing it over PM4K
upgrades in place and keeps your settings, servers and cache. Going back is the
same move in reverse — install pannal's zip over this one.

**Turn the in-app update check off.** PM4K's built-in updater still points at
`pannal/plex-for-kodi`, so left alone it will eventually offer, and install,
upstream over the top of this build. In the add-on's own settings:
**System → Check for updates**, off.

### Installing to a read-only location

Set `INSTALLATION_DIR_AVOID_WRITE` to any value before starting Kodi and the
add-on will not try to write to its own installation directory. Useful when a
package manager owns that path.

## Requirements

- Kodi 19 (Matrix), 20 (Nexus), 21 (Omega) or 22 (Piers)
- A Plex Media Server to talk to
- Optional and worth it: pannal's
  [Plextuary](https://github.com/pannal/skin.plextuary) skin

## Development

```sh
pip install -r requirements-test.txt
python3 -m pytest              # ~760 tests in ~10s, no Kodi and no network
python3 -m flake8 --count .    # the errors-only gate CI runs
```

The suite fakes the whole Kodi API (`tests/kodistubs/`), which is what makes the
add-on importable — and most of it testable — on a normal machine.
[`tests/README.md`](tests/README.md) covers how the fakes are steered, what is
covered, and the traps: Kodi state snapshotted at import time, module
singletons, multi-line `.po` entries.

CI runs on every push and pull request:

| Workflow | What it does |
|---|---|
| [`tests.yml`](.github/workflows/tests.yml) | pytest on Python 3.8 (Kodi 19/20), 3.11 (Kodi 21) and 3.14 (Kodi 22), plus a Windows leg; byte-compiles the add-on on 3.8, so the files no test imports still have to parse where they run; flake8, errors only |
| [`package.yml`](.github/workflows/package.yml) | builds the installable zip, checks it holds exactly one `script.plexmod/` folder with no test or CI files in it, and attaches it to the release on a `v*` tag |

Pull requests are welcome. Keep the suite green, cover behaviour you change, and
say in the PR whether it is specific to this edition or something that should go
upstream.

More background: [`docs/`](docs/) (subtitle selection, for one) and
[`path_mapping.example.json`](path_mapping.example.json) for local path mapping.

## Credits

- **Plex Inc.** — the original [plex-for-kodi](https://github.com/plexinc/plex-for-kodi) client.
- **[pannal](https://github.com/pannal)** — PM4K / PlexMod for Kodi: the client
  this edition is built on and the source of essentially every feature it has.
  If you get value out of this, that is where the credit belongs.
- **The Squad** — upstream's testers, listed in [TESTING_SQUAD.md](TESTING_SQUAD.md).
- **Translators** — the translations shipped here come from upstream's
  [POEditor project](https://poeditor.com/join/project/ASOl50YAXg). Contribute
  there, so every PM4K user gets them.

## License

[GPL-2.0-only](LICENSE.txt), inherited from the upstream project.
