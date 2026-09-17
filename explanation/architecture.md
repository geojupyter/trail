---
title: "🏛️ Architecture"
---

This document is the source of truth for architecture.

:::{note}
This document is a work in progress.
We are beginning prototyping and this document will be where we record the architecture
decisions we make during prototyping.

Any major architecture decisions should be recorded as decision records as well.
:::


## Open questions

* Data format for the Trailfile: Flat file? SQLite DB? Other?
* Data model - Event structure (Trail & compatible tools)
* Push/pull tracking (e.g. does JupyterGIS tell Trail what it did, or does Trail “watch” JupyterGIS like it would need to watch the filesystem for certain events?)
    * Probably pull 🙂 we want tools to provide event feeds that we pull from; we don't
      want tools to have to know how to speak "Trail".
