# Decoder scope and evidence

This package uses an independently written, standard-library Python reader of documented fields. It does not vendor the community repositories. Their code/specifications provided interoperability evidence; no upstream implementation is promised to handle every app version.

## Actual macOS store verified 2026-10-12

Default location: `~/Library/Containers/com.gingerlabs.Notability/Data/Library/Application Support/local-persistence-collab-production/`.

- `local_persistence`: SQLite/WAL database. `note_metadata.id` was observed as 16-byte UUIDs; associations must use both `noteId` and `userId`.
- `notes/<uppercase UUID>`: FlatBuffers root field 0 is a vector of operation tables.
- `assets/<128-character hash>`: original assets. Detect file signatures, not suffixes.
- `asr/<lowercase hash>.plist`: plain plist containing `segments`, each with `startTime`, `endTime`, `text`, `confidence`. Time values observed in seconds. Native transcript provenance uses the same hash as the audio asset.
- `asset_note_associations`: `assetHash`, `noteId`, `userId`.
- `legacy_note_recording_association`: `hash`, `noteId` supplements asset associations.

The ASR cache may be absent even if `asr_job_metadata` contains an entry. Not every stage means completed. Actual cache availability is authoritative for this reader. Asset associations can include multiple historic recordings and PDF assets; they do not by themselves reconstruct page order or recording order.

## Implemented formats

| Input | Implemented | Explicitly incomplete |
|---|---|---|
| Native Mac store | Selected assets/ASR, page refs/order/PDF backgrounds, ink deletes/restores/translations, epoch recording candidates | Native Note Replay validation, pause/import playback clocks, pressure/rotation/fragments, typed text/image placement |
| `.ntb` | `noteBundle` op vector field 6, same operation decoder, known media suffixes | Hash-to-member/ASR discovery in arbitrary exports; all native limitations above |
| `.note`/`.nbn` | Keyed archive UIDs, stroke arrays, two observed color encodings, text stringKey, replay UUIDs/timestamps/recording IDs, media and library recording IDs | Pressure, rotated groups, recognized shapes, page geometry and eraser reconstruction |
| External transcript | ASR plist, SRT, VTT, JSON segments, untimed TXT | Automatic speech recognition, arbitrary transcript schemas |

Ink point blobs implement documented f16/f32 cubic chains with strict byte-length checks. Unsupported fragment/erase paths are skipped with an explicit count. Modern previews omit pressure and rotation; compare official exports. Unknown versions must fail or disclose omissions, not invent associations.

## Local reverse-engineering, Mac 16.12.5 (7172)

Observed on one real 400-operation note; these fields are independently derived, not a vendor contract. Synthetic regression fixtures contain no private note bytes.

- IDs: op slot 0 is `(site, sequence)` u32×2. Page references are `(site, sequence, local_page_index)` u32×3; never infer a page from Y coordinates.
- Type 3 adds a page batch: payload slot 0 is the preceding page ref (absent = start); slot 2 is count (absent = 1). Slot 1 is a template: slot 3 gives dimensions; slot 1 points to PDF metadata, whose slot 0 asset table has inline 64-byte SHA-512 hash, filename string (1), MIME string (2). PDF-local pages correspond to batch indices. Imported dimensions are source dimensions, while ink uses the metadata's document width (612 pt in the sample): preserve aspect ratio and normalize width. Using 720×540 source slides directly shifted all handwriting.
- Type 4 reorders pages: payload slot 0 vector of 12-byte refs; slot 1 table slot 0 preceding-page ref. Missing anchors make page order unresolved.
- Type 25: payload slots 0/1 are vectors of 8-byte object IDs to delete/restore; slots 2/3 are 12-byte page-ID vectors to delete/restore. Object IDs and page refs have different widths.
- Type 24 translations: payload slot 0 vector of tables: object ID (0), page ref (1), new origin float32×2 (2), transform table (3). Only zero rotation is handled; original pen timestamps are retained. Other edit/group semantics are not validated.
- Type 5 recordings: payload `0.0` is an asset table; slots 1/2 are start/end Unix epoch milliseconds. Type 15 pen-down/up are op slots 3/2. A uniquely containing recording produces seconds `(pen_ms - start_ms)/1000`, with explicit candidate provenance. All 13 sample intervals equal `afinfo` saved-audio duration exactly. 320/321 surviving strokes fall inside unique recordings; one is unmatched. This does not establish paused/imported-audio behavior or independently validate native Replay.

Legacy replay mapping requires UUID identity. No sequential fallback is used. A shared recording ID and overlapping time ranges yield `temporal_candidates` with `semantic_match=false`.

Keyword matching uses Unicode normalization and whitespace-insensitive substring evidence. Temporal overlap is ranked first and keyword-only candidates are labeled separately. The skill must independently inspect meaning and handwriting. No match does not prove a concept was omitted from the lecture.

Parser limit: 128 MiB per parsed file/archive member; archive total 2 GiB and 10,000 entries. Local media files can be up to 2 GiB. `watch` keeps full snapshots and can consume significant disk space on long sessions. Sources are never overwritten; a new extract output must not already exist.

## Primary sources

- [PsychQuant NoteCore](https://github.com/PsychQuant/note-core-swift): legacy stroke/time decoder. `NBCPTimeManagerSOATimestampsKey`, `...DurationsKey`, `...RecordingIDsKey`, `...EventUUIDsKey`; recordings library fields `identifier`, `filepath`, `duration`.
- [PsychQuant HTML player](https://github.com/PsychQuant/note-to-html-swift): legacy audio-synced stroke replay precedent.
- [inkterop Notability specification](https://cable729.github.io/inkterop/docs/formats/notability/): modern FlatBuffers root/op fields, f16/f32 cubic paths, local store observations and incomplete erase semantics.
- [Notability Notes Converter](https://github.com/nokcha0/Notability-notes-converter): broader `.note`/`.ntb` format and conversion attempts.
- [Notability live transcription engineering](https://blog.notability.com/post/how-we-built-live-transcription): ink edit timestamps and transcript segment times; live and completed transcription may differ.
- [External audio import](https://support.gingerlabs.com/en-us/articles/16300111-importing-audio): MP3/MP4/M4A and transcription support; new handwriting during imported audio playback can sync.

## Next reverse-engineering checks

Independently compare derived times with native Note Replay at several strokes. Use a disposable controlled note (with explicit authorization to record/change it) for pauses, imported audio playback/seek, rotated groups, eraser fragments and undo of transforms. Keep external clocks separate. Current links remain labeled derived candidates until those cases are verified.
