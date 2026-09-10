# Trail Project Plan

## 1. Purpose

Trail is a local project record for geospatial workflows. It lives inside a project directory, like `.git`, and records which datasets belong to the project and how they change across tools.

The long-term goal is to reduce friction in Jupyter-based geospatial work by making implicit activity inspectable, reproducible, and attributable without tracking the user's code itself.

## 2. Immediate Milestone: OS Resource-Tracking Prototype

### Objective

Demonstrate this complete workflow on a small toy project:

1. Initialize Trail in a directory.
2. Explicitly register two or three files as resources.
3. Modify one registered file outside Jupyter by overwriting, renaming, or deleting it.
4. Run an on-demand status check.
5. Report what changed and identify the affected resource by its stable resource ID.

### Definition of done

- A project receives one persistent project ID at initialization.
- Each registered resource receives a persistent project-local ID independent of its path or filename.
- Resource registration records at least the path, size, and modification time.
- Status detects unchanged, modified, renamed/moved, and deleted resources.
- Detected changes are appended to a human-readable log.
- A small test suite proves the end-to-end scenario.
- The implementation uses the Python standard library unless a dependency is clearly justified.

### Explicitly out of scope

- Continuous filesystem watching or a background daemon
- Automatic registration of every project file
- IPython/Jupyter cell hooks
- JupyterGIS interaction events
- Databases, distributed synchronization, or CRDTs
- `push`, `pull`, remote storage, and web-wide tracking
- AI summaries, reports, or model-training pipelines

## 3. Prototype Design

### Project layout

```text
toy-project/
├── .trail/
│   ├── project.json     # Stable project metadata
│   └── trail.jsonl      # Append-only resource and event records
├── data-a.geojson
└── data-b.tif
```

### Core components

#### `Trail`

- Initialize or open a Trail project.
- Own the stable project ID.
- Register resources.
- Reconstruct current state from the append-only log.
- Compare recorded resource state with the filesystem.
- Append detected events and return a status report.

#### `Resource`

- Stable local resource ID
- Current project-relative path
- Recorded size
- Recorded modification time
- Optional file fingerprint if rename detection needs stronger identity

#### Filesystem inspection

- Use `pathlib` and `os.stat` for portable, on-demand checks.
- Treat missing registered paths as deleted unless a matching moved file is found.
- For the prototype, infer renames by scanning project files for a unique size/mtime match.
- Surface ambiguous matches instead of guessing.
- Consider content hashing later if reliable rename detection becomes necessary.

#### Append-only store

Use newline-delimited JSON: one immutable record per line.

Initial record types:

- `resource_registered`
- `resource_modified`
- `resource_renamed`
- `resource_deleted`

Each record should include:

- Record type
- UTC timestamp
- Project ID
- Resource ID
- Relevant path and filesystem metadata

## 4. Public Interface

Keep the Python API and any CLI vocabulary aligned:

```text
trail init [PATH]
trail add FILE [FILE ...]
trail status
```

Equivalent Python operations:

```python
trail = Trail.init(path)
trail.add(file_a, file_b)
changes = trail.status()
```

Avoid implementing Git-like commands such as `commit`, `push`, and `pull` until their semantics are defined and needed.

## 5. Implementation Sequence

### Phase 1 — Project identity and storage

- Create `.trail/` safely.
- Generate and persist a project ID once.
- Refuse accidental reinitialization or make it idempotent.
- Implement JSONL append and replay helpers.

### Phase 2 — Explicit resource registration

- Validate that each path exists and is inside the project scope.
- Assign a random project-local resource ID with a uniqueness check.
- Record project-relative path, size, and modification time.
- Prevent duplicate registration of the same resource path.

### Phase 3 — On-demand change detection

- Compare every active resource record with current filesystem metadata.
- Classify unchanged, modified, missing, renamed, and ambiguous states.
- Append new event records without duplicating already-recorded observations.
- Present results grouped by resource ID.

### Phase 4 — Tests and demonstration

- Initialization persists the same project ID when reopened.
- Registration assigns distinct stable resource IDs.
- Overwriting a file produces a modification event.
- Renaming a file preserves its resource ID.
- Deleting a file produces a deletion event.
- Unchanged files produce no new event.
- A second status call does not duplicate an acknowledged event.
- A scripted toy-project demonstration exercises the complete workflow.

## 6. Design Decisions to Resolve

1. **Status acknowledgment:** Should `status` update the stored baseline immediately, or should a separate command acknowledge changes?
2. **Rename identity:** Is a size/mtime heuristic sufficient for the prototype, or should registration also store a content hash?
3. **Resource scope:** Must resources be inside the project directory, or may Trail register external local files?
4. **Deletion lifecycle:** Can a deleted resource later be restored under the same ID?
5. **Log schema:** Which fields are mandatory now so later Jupyter and JupyterGIS event producers can share the same log?

Recommended prototype choices: let `status` append and acknowledge detected changes; restrict resources to the project directory; use size/mtime rename inference with explicit ambiguity reporting; and keep deleted resource IDs reserved.

## 7. Later Roadmap

### Jupyter kernel integration

- Subscribe to IPython pre-cell and post-cell events.
- Preserve execution order and notebook-switch context.
- Associate relevant resource changes with execution windows.
- Investigate existing IPython history before designing redundant storage.

### JupyterGIS integration

- Consume map and GUI event signals.
- Record meaningful actions such as opening a map, selecting data, changing layers, and changing the viewport.
- Coordinate with the existing JupyterGIS event-feed work.

### Optional real-time filesystem events

- Add a watcher only as a latency improvement over on-demand status.
- Keep filesystem comparison and log replay as the authoritative foundation.

### Provenance outputs

- Generate chronological workflow summaries.
- Export concise Markdown or LaTeX reports.
- Define optional profiles that control the level and type of reported detail.

## 8. Guiding Constraints

- Local-machine scope first
- Explicit data-resource registration
- Stable opaque IDs, never path-derived IDs
- Append-only, inspectable records
- Cross-platform behavior
- Minimal dependencies and small modules
- Provenance and accountability without indiscriminate data collection
- Design correctness before feature completeness

## 9. Deferred or Separate Work

The notes also mention Nominatim tests, monthly CI, dependency cleanup, `segtile`/`vectile` refactoring, and NumPy performance work. These appear unrelated to the Trail prototype and should be tracked in their respective repositories rather than included in this milestone.
