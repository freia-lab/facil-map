# Version 0.4.2 — 2026-10-26

Uses a crosshair when measuring distance or choosing calibration points,
landmarks, grid origin and replacement-plan alignment references. Panning
uses the grabbing cursor; ending survey mode restores the ordinary cursor.

# Version 0.4.1 — 2026-10-26

Adds broad fading bands behind grid row/column labels. Axis labels use quieter
text without individual outlines. Grid lines are faint short dashes with contrast
following the light/dark plan treatment independently of the app theme. Column
numbers remain at the top to keep the scale/status area clear.

# Version 0.4 — 2026-10-26

Adds administrator-only calibration, named landmarks, grid anchoring, validated
SVG upload, proportional two-reference plan registration with extra-reference
error checks, preview/cancel/apply, stale-write detection and revision rollback.
Existing accounts remain editors; designate admins using --set-role/--role.
No stored object coordinates or object history are changed during migration.

Adds dynamic scale bar, fixed 2 m grid with numbered columns/lettered rows,
plan-pixel cursor coordinates and cell references, temporary distance measuring,
collapsed numeric geometry editor, whole-shape translation and object duplication
with new IDs/history and unverified status. Photo files are reused for copies.

Uploaded plans are compressed/deduplicated in SQLite and included in backups.
No SVG snapping or continuous copy placement is included. See README for SVG
restrictions, calibration workflow and rollback behavior.

# Version 0.3 — 2026-10-14

Adds two aligned floors with preserved camera position, bounded navigation,
current/all-floor search, immediate object editing in explicit edit mode,
dirty-state tracking, selective save/discard/keep prompts, and readable concurrent
edit comparison with independent-field merging.

Adds immutable resized identification photos, main-photo/caption editing,
historical photo recovery, and incremental image-pool backups with manifests
and validated restore.

Adds reviewed, atomic CSV import and matching editable export for all shapes,
globally stable external IDs, stale-preview detection, and recorded import batches.
No cable-database integration is included.

Adds Light grey, Solarized light, and Black to Light/Midnight, plus independent
plan treatment. Preferences remain browser-local.

Caches map objects, schedules pointer rendering, and avoids full unchanged
poll responses. Includes isolated 100/300/1000-object benchmark generation and
an optional local browser measurement tool.

Migrates earlier databases additively with a pre-upgrade backup. Photos add the
Pillow dependency; launchers install it when needed.

# Version 0.2 — 2026-10-13

Midnight theme, fixed panes, persisted editable layers, circles/slots, edit-mode
border/badge, temporary editing lifecycle, anchored confirmations, idle timeout fix.
