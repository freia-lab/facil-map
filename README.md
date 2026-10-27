# FREIA facility map — prototype 0.3

A self-hosted intranet app for finding services, marking equipment and areas,
and maintaining information, photos, and revision history on two aligned floor plans.

## Start or upgrade

Requires **Python 3.10+** and **Pillow 12.3+** for image processing. No Node.js or
separate database server is needed to run the app. The launcher installs Pillow
when it is missing or older; that first installation requires package access.
Normal application operation uses only locally served assets.

1. Extract the complete ZIP to a writable folder.
2. Windows: double-click **start-windows.bat**. Linux/macOS: run `./start.sh`.
3. Open **http://127.0.0.1:8000** in your browser and keep the command window open.
4. Stop with Ctrl+C. Closing just the browser does not stop the server.

For manual installation/start:

```sh
python -m pip install -r requirements.txt
python server.py
```

Use `python3` on systems where that is the Python command. For another port,
run `python server.py --port 8001` and open http://127.0.0.1:8001.

**Upgrading an existing installation:** stop it, back up its complete `data`
folder, extract the new app into a separate folder, and copy the old `data`
folder into the new `freia-map` folder. Launch the new app and press Ctrl+F5 in
the browser. Do not run both versions on the same database. See **UPDATING.txt**.

The first start seeds seven illustrative objects on the ground floor. The upper
floor initially has no objects. Every sample location and technical value is
invented; the supplied CAD drawing may itself contain outdated facility details.

## Floors, navigation, and searching

Select Ground floor or Upper floor above the map. Both currently use the same
SVG, as a placeholder, and have separate object sets. Switching floors keeps the
same camera position and zoom. Floor selection is remembered in the browser.

Pan by dragging, zoom using the wheel or +/- buttons, and use the fit button to
show the plan. Keyboard arrows and +/- work when the map has focus. Navigation
is bounded to the plan plus a 40-plan-unit margin. Axes that already fit entirely
in the viewport stay centred, including on tall or narrow windows. Side panes
scroll independently; the page and central map stay within the window.

Search names, descriptions, technical details, keywords, link labels, and layer
aliases. "Pressurized air", "compressed air", and "tryckluft" match the default
compressed-air layer. Search defaults to the active floor. **Search all floors**
includes the other floor; selecting one of its results switches there. Search
results show the floor name. Layer checkboxes affect both search and the map.

Layers are shared across floors. **Map layers → Manage** adds/edits layers,
colours, marker symbols, and search aliases. Removing a populated layer requires
reassigning its active and recoverable deleted records to another layer. History
is retained, reassignment is atomic, and at least one active layer must remain.
Layer-definition revisions are included in JSON exports; the UI does not yet
restore old layer definitions. Restoring an object from a removed layer follows
that layer's successor to an active destination.

## Editing and unsaved changes

Sign in, enable **Edit mode**, and click an existing object to edit its properties
and shape immediately. The red border and EDITING badge mark the mode. Explicit
edit mode stays active while you move between objects.

Opening **Edit object** from viewing mode starts a temporary edit session;
saving/cancelling returns to viewing. The Unsaved changes indicator compares the
current information, photo references, and geometry with the saved snapshot.
Changing a value and changing it back clears the indicator.

- An unchanged existing draft can be abandoned or switched without a prompt.
- Switching from a changed draft offers **Save and switch**, **Discard and
  switch**, or **Keep editing**.
- A failed/conflicting save retains the draft and prevents that switch.
- Cancel asks before discarding actual changes, near its button.
- New drawn objects count as unsaved until saved.
- Browser navigation warns about changed drafts; drafts are not a crash-recovery
  mechanism and are not stored across forced reloads.

Drag the shape body to move it or white handles to reshape it. Shapes:

| Shape | Drawing | Handles |
|---|---|---|
| Point | One click | Position |
| Rectangle | Two opposite corners | Opposite corners |
| Circle | Centre, then edge | Centre moves whole circle; edge changes radius |
| Slot | Two end centres, then width | End centres change length/orientation; width handle changes thickness |
| Polygon | Vertices, then Finish shape/Enter | Corners |
| Line | Route points, then Finish shape/Enter | Route vertices |

A slot is a capsule with semicircular ends and may have any orientation. Entire
circles/slots must fit within the plan. Escape cancels drawing. Technical details
use one `label | value` per line; links use one `label | address` per line. Links
support HTTP, HTTPS, and root-relative web paths, not local/network-drive paths.

Every object has a globally unique **External ID** for repeated CSV imports.
Leaving it blank on creation generates an ID. Prefer readable IDs such as
`G-AIR-001` and `U-AIR-001` if maintaining external lists. Changing an ID changes
which future CSV rows match it.

## Concurrent edits and history

The server checks object revision numbers inside SQLite write transactions.
A stale save never silently overwrites another editor. On a conflict, use
**Compare and combine changes**:

- The comparison shows original, latest saved, and your draft values.
- Independent changes are combined into a draft automatically.
- If both sides changed the same field, choose which value to use.
- Geometry and floor form one location field, so a floor move is not blindly
  combined with a shape change from the other editor.
- Reviewed changes remain unsaved until you Save. The revision check runs again.
- A deleted object must be restored before editing; the conflict keeps your draft.

Array fields such as technical details, links, and photo references are compared
as whole fields; individual rows are not automatically merged. There are no
exclusive edit locks or live typing indicators. Other users' saved records are
checked every 15 seconds while browsing. Open drafts pause background refresh.
Unchanged checks return a small token response rather than the whole object list.

History stores complete information/geometry/photo-reference snapshots. Delete
hides an object, and Recent changes can find it for restoration. Restore makes a
new revision. Copy link shares a direct object URL, which switches to its floor.
A localhost URL works only on your computer; use your internal server hostname
when sharing with colleagues.

## Identification photos

In the editor, add JPEG/PNG files, captions, and a main identification image.
Thumbnail clicks open larger photos. Save commits photo references alongside the
object; removing a photo from the editor is also committed only when you Save.

Uploads allow up to 12 MB and 40 megapixels per source image, and up to 20 photos
per object. The server applies orientation, resizes the long edge to at most
1600 pixels, stores a JPEG, and strips original metadata. Identical processed
images share a content hash. Original camera-resolution files are not retained.
Photos are loaded from thumbnails only when the record is opened; they are not
embedded in routine map-data responses. Photo-processing concurrency is bounded.

Files live in **data/images/**. Original processed JPEGs are immutable; thumbnails
are derived and regenerated if missing. Old photo references remain usable in
history. Uploaded files that were never attached may remain in live storage;
backup includes only files referenced by current records or retained history.
Automatic image/history garbage collection is intentionally not implemented.

## Editable CSV import and export

Use **Import → Download CSV template**, or start from **examples/objects.csv**.
The example file has one of every shape, marked as sample data. Use your actual
layer names if defaults have been renamed/removed.

Import steps:

1. Sign in and choose a UTF-8 CSV file (up to 2 MB and 5,000 records).
2. Preview it. Review additions, updates, unchanged records, changed fields,
   and errors. Nothing has been written yet.
3. Fix any errors and preview again. An import with errors cannot be applied.
4. Apply the reviewed changes. The server rechecks object and destination-layer
   revisions. If anything relevant changed after preview, preview again.

Imports are atomic and create a recorded batch. Existing rows match by external
ID. Missing rows do not delete objects. Photo references on updated objects are
preserved. Deleted IDs cannot be reused until their records are restored, or a
new ID is chosen. Previews expire after 20 minutes and are tied to the signed-in
user; applying the same preview twice is rejected.

**Export data → Download editable CSV** uses the same format. The complete JSON
export includes records, object/layer history, photo metadata, floors, and import
batches; it does not include binary image files or user credentials. JSON import
is not implemented. Use the backup/restore scripts for full recovery.

### Columns

Required: `external_id,name,floor,layer,shape,coordinates`.

Optional: `radius,description,status,tags,details,links`.

| Column | Meaning |
|---|---|
| external_id | Unique stable ID across both floors |
| name | Object name |
| floor | `ground` or `upper`, or the configured floor name |
| layer | Active layer name or ID; create missing layers before importing |
| shape | `point`, `rectangle`, `polygon`, `line`, `circle`, or `slot` |
| coordinates | Ordered `(x,y)` pairs, separated by commas |
| radius | Circle radius or slot end radius (half-width) |
| description | Free text |
| status | `unverified`, `verified`, `out-of-service`, or `sample` |
| tags | Keywords separated by `|` |
| details | One `label | value` per line inside the cell |
| links | One `label | URL` per line inside the cell |

Point: one position. Rectangle: two opposite corners. Polygon/line: ordered
vertices. Circle: one centre plus radius. Slot: two end centres plus radius.
Coordinates use dot decimals and visible-plan units, not metres.

```csv
external_id,name,floor,layer,shape,coordinates,radius
G-AIR-001,West outlet,ground,Compressed air,point,"(295,445)",
U-AREA-001,Storage,upper,Areas,rectangle,"(200,300),(400,500)",
G-ZONE-001,Circular zone,ground,Areas,circle,"(600,300)",40
U-ZONE-001,Slot zone,upper,Areas,slot,"(600,300),(750,400)",20
```

Quote coordinate fields in comma-delimited CSV; spreadsheet software does this
when exporting. Semicolon/tab delimiters and a UTF-8 BOM are accepted. Exported
formula-like text is protected with a leading apostrophe, which the importer
recognises; original leading apostrophes are escaped so round trips preserve them.

An omitted optional column preserves the corresponding field on updates. A
present empty description/tags/details/links cell clears it. Blank status uses
unverified. Required fields must be supplied. Unknown/duplicate headers are
rejected rather than silently dropped. CSV excludes photos and prior revisions;
an import adds new revisions to the application's own history.

## Themes

Select Light, Light grey, Solarized light, Midnight, or Black in the upper right.
Solarized light uses a cream/sepia background with dark text. **Plan: auto/light/dark**
controls the drawing separately. Auto follows the selected theme; light keeps a
white plan even with dark surrounding panels.

Preferences are remembered in browser local storage, per browser profile and
site origin. Moving between localhost and the intranet hostname creates separate
preferences. Private browsing or disabled/cleared storage may reset them.

## Backups, image retention, and restoration

Create a snapshot while the app is running:

```sh
python scripts/backup.py
```

This writes a timestamped SQLite snapshot and a `.sqlite3.manifest.json` alongside
it. The manifest identifies referenced images from both current records and
history. Newly needed processed JPEGs are copied to **backups/images/**. Repeated
backups reuse unchanged hash-named files; thumbnails are not copied.

Custom locations:

```sh
python scripts/backup.py --data /path/to/freia.sqlite3 --output /backup/snapshot.sqlite3 --image-store /backup/images
```

**Keep the database, manifest, and referenced image pool together.** A database
snapshot alone cannot recover photos whose files are missing. Do not remove an
image while a retained snapshot or retained history refers to it. This version
keeps history/images and has no automatic retention pruning.

Restore after stopping the server:

```sh
python scripts/restore.py /backup/snapshot.sqlite3 --data /path/to/freia.sqlite3
```

The script verifies database/image hashes and SQLite integrity before replacing
the target, restores required JPEGs, and backs up an existing target database.
It regenerates thumbnails on later requests. Snapshots from before photo support
can be restored without an image manifest if they have no photo references.
Users sign in again after server restart.

For containers:

```sh
docker compose exec map python scripts/backup.py --data /data/freia.sqlite3 --output /data/backups/snapshot.sqlite3 --image-store /data/backups/images
```

Choose a new snapshot filename each time. Arrange protected off-server copies
using IT's normal backup tooling; a backup inside the same Docker volume does
not protect against volume loss.

## Shared intranet hosting

All signed-in accounts can edit. Viewer access does not require app login;
restrict the service to the intended intranet audience or an access-controlled
reverse proxy. The default local demo binds only to your computer, and its names
label edits but do not verify identity.

Create accounts and run in shared mode:

```sh
python server.py --create-user piotr
python server.py --create-user another-user
python server.py --host 0.0.0.0 --auth accounts
```

Account creation prompts for a password of at least ten characters. Repeating
it updates that password. Account names are case-sensitive. The app stores
salted PBKDF2 hashes and attributes changes to accounts. Shared-interface binding
is refused in demo mode. Organisational SSO is not integrated.

IT should configure internal DNS/firewall rules, HTTPS and process supervision.
Use `--secure-cookie` when accessed through an HTTPS reverse proxy, with the
original Host header preserved. Forward the entire site, including `/api/`,
`/assets/`, and `/media/`; use a dedicated hostname rather than a URL subdirectory.
The standard-library threaded server is intended for a small intranet pilot;
review the serving setup before wider production use. SQLite belongs on local
persistent disk, not a network-share database file.

Docker:

```sh
docker compose build
docker compose run --rm map python server.py --data /data/freia.sqlite3 --create-user piotr
docker compose up -d
```

The `map-data` volume contains the database AND photo files. Building needs access
to the Python image and Pillow package; normal running needs no public internet.
Do not remove that volume unless intentionally erasing records and photos.

## Replacing the drawings

**floors.json** names the floors, their URLs, and the shared width/height. Both
currently point to `/assets/plan.svg`. To replace only the upper drawing, put an
aligned SVG at `static/assets/upper-plan.svg` and change the upper floor's URL.
Restart after changing floor configuration. No floor-manager/upload UI is included.

The two drawings must have the same physical alignment, orientation, scale, and
visible coordinate frame; simply stretching a different crop to fit will misalign
records and break same-view switching. Empty upper-floor space should remain in
the shared frame. The app rejects differing frame dimensions in floor configuration.

`plans/original.svg` preserves the uploaded drawing; `plans/metadata.json` records
its preparation. The original viewBox is `80 220 1440 720`, mapped to an application
frame with top-left `(0,0)` and size `1440 × 720`. The prepared SVG retains geometry,
groups about 82,000 paths into 320, and transfers at about 1.25 MB gzip-compressed.
Its small raster differences at stroke overlaps come from antialiasing.

If replacing a prepared SVG, also regenerate its `.svg.gz` companion or remove
the stale companion so the server compresses the current SVG. Keep a record of
plan alignment before populating large amounts of facility data.

## Performance measurement

Map object elements are cached and retained during navigation. Pan-only frames
do not recreate them; zoom updates screen-sized markers/labels. Pointer updates
are scheduled once per animation frame. Search uses cached match results, images
load only in detail views, and unchanged polling avoids retransmitting objects.

Generate a separate test database; existing files are never overwritten:

```sh
python scripts/benchmark_data.py --count 100 --output performance/100.sqlite3
python scripts/benchmark_data.py --count 300 --output performance/300.sqlite3
python scripts/benchmark_data.py --count 1000 --output performance/1000.sqlite3
```

Stop the normal app, then test one at a time:

```sh
python server.py --data performance/300.sqlite3
```

Open **http://127.0.0.1:8000/?benchmark=1**, choose **Export data → Measure map
performance**, and record the result. The test temporarily moves/zooms the camera
through 120 frames, then restores it. It reports visible/total object counts,
median and 95th-percentile frame intervals, approximate initial load time, cached
group count, and browser heap size where supported. These are browser scheduling
measurements, not isolated drawing durations. Do not run with an open draft.

Datasets mix points, rectangles, 24-vertex polygons, routes, circles, and slots,
including dense clusters and both floors. Also manually test search/selection,
geometry dragging, repeated floor switching, labels on/off, and periodic refresh.
Compare on typical facility workstations, with the same browser, viewport, and
settings. Measure cold and warm loading separately. The generated database
contains no real facility data and no photos; photo workflows should be checked
separately using representative uploads.

Actual browser frame-rate measurements were not available in the build
environment. A benchmark is included so those measurements can be made locally.

## Verification and scope

Backend checks:

```sh
python -m unittest discover -s tests -v
```

Optional controller checks need Node.js (not needed for the app):

```sh
node --check static/app.js
node --check static/v03.js
node tests/test_ui_logic.cjs
node tests/test_v03_ui.cjs
```

Tests cover old-schema migration, account preservation, revision conflicts, layer
reassignment/recovery, floors/IDs, every CSV shape round trip, stale/atomic imports,
image processing/deduplication, historical photo recovery, incremental backup and
restore, quiet idle vs visible real timeouts, dirty/reverted fields, selective
switch prompts, camera bounds, preserved floor view, conflict merging, themes,
and reused map nodes. Controller tests use a small DOM stub, not a browser engine.

**Visual browser interaction and Docker deployment were not available for full
end-to-end verification.** Check layout, dialogs, photo display, and drawing in
your browser before wider use. No cable-database integration, SSO, offline edit
queue, automatic image/history pruning, PDF/CAD import, snapping, or measurement
tools are included in this update. Technical details remain flexible per object.

## Version 0.4: measurement and plan setup

The status bar displays X/Y in **plan pixels**, with (0,0) at the original
visible top-left, X right and Y down. These are stable SVG drawing units,
not screen pixels or pixels measured in a resized screenshot. Existing objects
and CSV coordinates retain their original coordinate system.

### Administrator access

Existing accounts remain editors. On the server, designate an existing account:

```sh
python server.py --set-role piotr --role admin
```

Replace `piotr` with the actual username; use `python3` on Linux as appropriate.
Create a new account first with `--create-user` if necessary. Remove setup
privileges with `--set-role USERNAME --role editor`. Roles are enforced on the
server for every setup write. Sign in again after changing a role to refresh
the visible controls. All signed-in names in localhost-only demo mode may use
setup; demo names are not authenticated administrators on a shared network.

### Calibrate and use measurement tools

An administrator opens **Map setup**, enters a known distance in metres and
its equivalent length in plan pixels, then presses **Set scale / select two
points**. Leave the pixel length blank to select the two points visually.
Pan/zoom during selection; clicks must be inside the fixed plan frame.
Use a long structural dimension. **Check another known distance** reports the
measured length and percentage difference without overwriting calibration.
A perpendicular dimension helps detect a stretched drawing.

Press **Apply setup** to commit. There is no assumed real-world scale in the
release. Until calibrated, the metric tools are disabled. Calibration is shared
across floors. Use **Choose grid anchor** to position the top-left of cell A1;
rows increase down and columns right. Locations above/left of the anchor are
outside the labeled grid. Moving the anchor changes cell references.

**2 m grid** toggles a fixed grid with numbered columns and lettered rows.
Labels sit at viewing edges; some labels are omitted at low zoom to avoid
crowding, without changing cell size or identity. The status bar includes the
cursor's cell. A dynamic scale bar stays visible when calibrated.

**Measure** activates a temporary two-click straight-line measurement in the
floor plane. It previews after the first click, and the next click after a
completed measurement starts another. Drag to pan; zoom normally. Escape or
toggling Measure clears and exits. Measurements do not create saved objects
and do not account for elevation or routed cable length.

### Object geometry and copies

Edit an object and expand **Advanced · Position and geometry** for numeric
plan-pixel control points. Focusing a coordinate highlights its vertex. Dragging
updates the numeric values. **Move whole shape** translates all vertices by
ΔX/ΔY, preserving dimensions. Circle control points are centre and edge; slot
points are its two end centres and a width handle. Invalid/outside geometry is
rejected by the editor or by final server validation. Ordinary Save, Cancel,
history and optimistic conflict handling still apply.

**Duplicate object** creates an unsaved copy. Click its new location, review
properties, and Save. The copy has a new ID/external ID and history, a title
ending in “— copy”, and unverified status. Photos reference existing immutable
files. The original does not change. Escape ends placement without discarding
the draft; Cancel discards the draft through the normal confirmation flow.

### Landmarks and replacement SVG drawings

In **Map setup**, name and place at least two permanent structural references.
References share the original plan frame between floors; choose references
visible on the floor drawing being replaced. Selecting the same physical
features on both floors preserves vertical alignment.

Choose the target floor before opening setup. Select the reference checkboxes,
then upload a replacement SVG. The release supports plain SVG groups and
geometric paths/shapes with a valid viewBox, up to 24 MB. Convert text and
reusable symbols to paths; embedded images, stylesheets, links, scripts,
external references and document declarations are not supported. Export from
Inkscape as a clean path-based drawing if validation rejects a CAD export.

Click the corresponding references on the NEW drawing in the listed order.
The first two calculate translation, rotation and uniform scale. Extra
references report positional errors in plan pixels; this is a consistency
check rather than an automatic distortion correction. If errors are large,
repeat the alignment or check the source drawing. Use well-separated references.
**Return to setup** can interrupt selection; incomplete alignment cannot apply.
**Inspect preview** lets you pan and zoom beneath existing objects before
committing. Cancel restores the saved drawing. Apply publishes the new
background for that floor; it does not move objects, grid references or the
camera. Other clients receive changes on their next refresh (normally 15 s
when not editing). A concurrent administrator save is rejected as stale.

**Show setup revisions / rollback** restores the calibration, landmarks, grid
anchor and BOTH floor backgrounds of a selected revision, recording a new
revision. Uploaded plans are sanitized, compressed and deduplicated by content
inside SQLite. They and all setup revisions are therefore included in database
backups and restored by the existing backup tools. This increases snapshot
size for each distinct uploaded plan; photo backup behavior is unchanged.
Canceled uploads may remain as deduplicated assets; no automatic asset pruning
is performed. JSON exports contain current setup metadata but do not embed SVG
or photo bytes; use backups for full recovery.

### Linux launch

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

On Ubuntu/Debian install `python3-venv` if the environment creation command
requires it. Activate `.venv` in each new terminal before launching. For shared
hosting, designate the administrator and use `--host 0.0.0.0 --auth accounts`.
