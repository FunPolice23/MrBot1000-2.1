"""
agents/platforms/__init__.py ? ARCH-ENG-205: the eager adapter re-export is gone.

This module used to import all five platform adapters plus the registry at
import time:

    from .base import PlatformAdapter
    from .fiverr import FiverrAdapter
    from .upwork import UpworkAdapter
    from .prolific import ProlificAdapter
    from .github import GitHubAdapter
    from .reddit import RedditAdapter
    from .registry import (...)

Every one of those eleven names had ZERO references anywhere outside this
package. They were not dead by accident -- they were unreachable, and the only
thing keeping them load-bearing was this file.

## Why that mattered so much

Python executes `__init__.py` before *any* submodule, so `from
agents.platforms.credential_vault import CredentialVault` -- which
`registration_panel.py`, `provider_keys.py` and `moltbook_agent.py` all do --
dragged in 1,103 lines of adapter code on every registration panel build.

That produced a genuinely confusing state, and it is why two independent
dead-code sweeps got this backwards in both directions:

* "nothing imports the adapters, so they are dead" -- true, and yet
* "deleting them breaks startup" -- also true

Both statements hold at once. The modules were reachable (via the package init)
and their contents unreferenced. A reachability tool reports the module as
reachable and the adapters as unused; neither fact implies the other.

## What remains here

`credential_vault` and `registration` are genuinely live, with real importers.
They are imported as submodules directly, which is what the package should
have looked like all along.
"""
