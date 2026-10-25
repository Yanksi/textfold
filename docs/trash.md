# Trash

The sidebar and collapsed sidebar have a Trash entry. Its dialog lists document
titles, IDs and deletion dates, with Restore and confirmed Delete permanently
actions. These use the document-oriented storage interface; neither the UI nor
the HTTP handler knows directory paths, SQLite tables or cloud object keys.

## Backend contract

All `StorageBackend` implementations provide:

- `trash(document_id, placement=None)`: retain the document and library placement.
- `list_trash()`: lightweight rows containing `id`, `title`, `deleted_at` (Unix
  seconds), `revision` (opaque confirmation token), `restorable`, `can_delete`.
  Cloud rows also report `pending` and `recovery`. Listing never downloads PDFs.
- `restore(document_id, revision=None)`: restore contents and return placement;
  return `None` when absent or an active copy already exists.
- `delete_trashed(document_id, revision=None)`: erase only the selected trashed
  identity, returning whether one existed; never delete an active document.
- `purge(before)`: backend retention policy. Local directories retain their
  existing 30-day cleanup. Cloud trash requires explicit permanent deletion.

Restore and permanent deletion reject stale non-null tokens with `ConflictError`.
The UI always supplies the listed token. Local tokens cover all retained copies
of that ID and their file metadata; cloud tokens refer to the local snapshot,
with a second cloud revision check before destructive publication.

`GET /api/trash` returns these rows. `POST /api/papers/restore` accepts
`{papers: [id], revisions: {[id]: revision}}`; `POST /api/trash/delete` accepts
`{paper: id, revision}`. Stale confirmations return HTTP 409. Existing undo
clients may omit revisions. No optional filesystem capability is required.

## Local and cloud safety

Local deletion removes recognized retained copies only. Active copies and other
documents remain intact. Symlinks and Windows junctions are removed as links,
leaving external originals untouched. Existing local libraries stay in place.

Cloud trash/restore work offline for downloaded documents and use the durable
outbox. Restoring an uncached document requires a connection. Permanent deletion
requires a connection to a service advertising `trash_purge: 1`, a synchronized
trash revision, no pending/uncertain edits or conflicts, and no active generation.
The intent is persisted before sending; local records remain until its exact
operation and outbox generation are acknowledged. A restart or lost response
cannot lose the intent or publish it twice. A concurrent remote restore/edit
cancels destructive intent and asks the user to review again.

The service atomically removes document records and publishes a terminal
`purged` tombstone with an idempotent operation and feed event. Even a client
with the newest revision cannot restore or recreate that ID. Old clients that
try merging into the tombstone receive 409. Other devices retain unacknowledged
edits, uncertain requests and generation replies as protected recovery data,
shown in Trash and exportable using Storage settings → Export pending changes.
Cache cleanup and retention never discard these copies. They cannot upload
against the purged identity; recovery under a new ID requires an explicit import.

This is application-level deletion, not secure erasure of all historical bytes.
R2 recovery snapshots and content-addressed blobs can be shared by revisions or
other documents and are not blindly deleted. Safe orphan garbage collection is
separate; do not remove a blob simply because one document was purged.

SQLite upgrades add columns in place without rewriting existing records or the
outbox. Cloud migration `0004_trash.sql` retains existing rows. Legacy cloud trash
is indexed by its latest retained token and can be restored losslessly after the
v2 fence; permanent deletion removes retained rows for that ID. An active same-ID
legacy document takes precedence and cannot be purged via the trash endpoint.

Regression tests use disposable libraries, real local D1/R2 and simulated devices.
They cover stale confirmation, restore, permanent deletion, rollback, lost
acknowledgements, restart, concurrent restore, offline recovery/export, active
generation, legacy migration, shared blob safety and external links. Browser
verification covers confirmation cancellation, errors/retry, collapsed sidebar
and narrow screens.
