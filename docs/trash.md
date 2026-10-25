# Trash

The sidebar's Trash button opens deleted documents from the selected library.
The collapsed sidebar has the same entry. Each row shows the document's title,
identifier and deletion date, with Restore and Delete permanently actions.

Restore uses the existing restore route: the latest retained copy returns with
its original source, notes, generated levels and folder placement. If an active
document already has that identifier, restoration is disabled; it is never
overwritten. A concurrent change is reported and the list can be reloaded.

Delete permanently requires confirmation. It removes every retained copy of
that identifier from this library's trash, including notes and generated levels.
It cannot remove an active document. A symbolic link or Windows directory
junction is removed as a link, leaving its external original untouched. Other
documents and folders that do not follow the recognized trash naming convention
remain intact. The existing 30-day startup cleanup remains in place.

`GET /api/trash` lists `{id, title, deleted_at, restorable}` rows without loading
PDFs or images. `POST /api/trash/delete` accepts `{paper: id}`. Backends may
implement the optional `TrashBrowser` capability (`list_trash`,
`delete_trashed`); an unsupported backend returns HTTP 501. Physical layout stays
inside the backend. The UI contains no directory paths.

Tests use disposable libraries and cover browsing, restoration, permanent
deletion, multiple retained copies, active-copy protection, unrelated files,
invalid identifiers/dates and external-link protection. Browser verification
covers confirmation cancellation, deletion, restoration, reopening, the
collapsed sidebar and narrow screens.
