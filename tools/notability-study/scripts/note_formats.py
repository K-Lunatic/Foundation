"""Small read-only decoders. Field provenance and limits: references/formats.md."""
import collections
import math
import plistlib
import re
import struct


def blank(fmt):
    return {"format": fmt, "strokes": [], "timeline": [], "segments": [], "media": [],
            "text_items": [], "warnings": []}


def unpack(data, fmt):
    if not isinstance(data, bytes) or len(data) % struct.calcsize(fmt):
        raise ValueError("Invalid binary array length")
    values = [v[0] for v in struct.iter_unpack("<" + fmt, data)]
    if any(isinstance(v, float) and not math.isfinite(v) for v in values):
        raise ValueError("Non-finite binary coordinate/time")
    return values


def stroke(stroke_id, points, path, width, rgba, **extra):
    if not points or not all(math.isfinite(x) and math.isfinite(y) and abs(x) < 1e7 and abs(y) < 1e7 for x, y in points):
        raise ValueError("Invalid stroke coordinates")
    if not math.isfinite(width) or not 0 < width < 10000:
        raise ValueError("Invalid stroke width")
    return {"id": stroke_id, "path": path, "width": width, "rgba": rgba,
            "bounds": [min(p[0] for p in points), min(p[1] for p in points),
                       max(p[0] for p in points), max(p[1] for p in points)], **extra}


def read_legacy(archive):
    note = blank("legacy-note")
    objects = archive.get("$objects", [])
    def deref(value):
        seen = set()
        while isinstance(value, plistlib.UID) or (isinstance(value, dict) and set(value) == {"CF$UID"}):
            i = value.data if isinstance(value, plistlib.UID) else value["CF$UID"]
            if not isinstance(i, int) or not 0 <= i < len(objects) or i in seen:
                raise ValueError("Invalid/cyclic archive reference")
            seen.add(i)
            value = objects[i]
        return value
    root = deref(archive.get("$top", {}).get("root", archive.get("$top", {}).get("$0")))
    if not isinstance(root, dict):
        raise ValueError("Missing keyed-archive root")
    name = deref(root.get("name"))
    if isinstance(name, str):
        note["title"] = name
    uuid_to_id = {}
    for oi, raw in enumerate(objects):
        if not isinstance(raw, dict):
            continue
        if "stringKey" in raw:
            text = deref(raw["stringKey"])
            if isinstance(text, str) and text.strip():
                note["text_items"].append({"id": f"text-{oi}", "text": text, "position": None})
        if "curvespoints" not in raw:
            continue
        points = unpack(deref(raw["curvespoints"]), "f")
        counts = unpack(deref(raw.get("curvesnumpoints", b"")), "I")
        widths = unpack(deref(raw.get("curveswidth", b"")), "f")
        colors = deref(raw.get("curvescolors", b""))
        uuids = deref(raw.get("curveUUIDs", b""))
        if len(points) != 2 * sum(counts) or len(widths) != len(counts) or any(n < 1 for n in counts):
            raise ValueError("Inconsistent legacy stroke arrays")
        if len(colors) not in (4 * len(counts), 12 * len(counts)):
            raise ValueError("Unrecognized legacy color encoding")
        rgb_floats = unpack(colors, "f") if len(colors) == 12 * len(counts) else None
        offset = 0
        for i, count in enumerate(counts):
            xy = list(zip(points[offset:offset + 2 * count:2], points[offset + 1:offset + 2 * count:2]))
            offset += 2 * count
            sid = f"stroke-{oi}-{i}"
            path = "M " + " L ".join(f"{x:g},{y:g}" for x, y in xy)
            rgba = [round(max(0, min(1, v)) * 255) for v in rgb_floats[i * 3:i * 3 + 3]] + [255] if rgb_floats else list(colors[i * 4:i * 4 + 4])
            note["strokes"].append(stroke(sid, xy, path, widths[i], rgba))
            if len(uuids) >= (i + 1) * 16:
                uuid_to_id[uuids[i * 16:(i + 1) * 16]] = sid
    manager = deref(root.get("contentPlaybackEventManager"))
    if isinstance(manager, dict):
        prefix = "NBCPTimeManagerSOA"
        def field(short):
            return deref(manager.get(prefix + short + "Key", manager.get("SOA" + short + "Key", b"")))
        starts, durations, recordings = unpack(field("Timestamps"), "f"), unpack(field("Durations"), "f"), unpack(field("RecordingIDs"), "H")
        ids = field("EventUUIDs")
        declared = deref(manager.get(prefix + "NumEventsKey", len(starts)))
        if len(starts) != len(durations) or len(starts) != len(recordings) or declared != len(starts):
            raise ValueError("Inconsistent replay timeline arrays")
        for i, (start, duration, rid) in enumerate(zip(starts, durations, recordings)):
            if start < 0 or duration < 0:
                raise ValueError("Invalid replay time")
            sid = uuid_to_id.get(ids[i * 16:(i + 1) * 16])
            if sid:
                note["timeline"].append({"stroke_id": sid, "recording_id": str(rid), "start": start, "end": start + duration})
        if len(note["timeline"]) != len(starts):
            note["warnings"].append("Some replay events lack a verified stroke UUID; no sequential fallback used")
    note["warnings"].append("Preview omits pressure, transforms, recognized shapes and PDF page layout; inspect official PDF for exact appearance")
    return note


class Table:
    def __init__(self, data, pos):
        self.data, self.pos = data, pos
        self.vpos = pos - self.number("i", pos)
        size, self.object_size = self.number("H", self.vpos), self.number("H", self.vpos + 2)
        if not 4 <= size <= 1024 or size % 2 or self.object_size < 4:
            raise ValueError("Invalid FlatBuffers table")
        self.bounds(self.vpos, size)
        self.bounds(pos, self.object_size)
        self.slots = (size - 4) // 2

    def bounds(self, pos, size):
        if pos < 0 or size < 0 or pos + size > len(self.data):
            raise ValueError("FlatBuffers offset out of bounds")

    def number(self, fmt, pos):
        self.bounds(pos, struct.calcsize("<" + fmt))
        return struct.unpack_from("<" + fmt, self.data, pos)[0]

    def field(self, slot):
        if slot >= self.slots:
            return None
        rel = self.number("H", self.vpos + 4 + slot * 2)
        if not rel:
            return None
        if not 4 <= rel < self.object_size:
            raise ValueError("Invalid field offset")
        return self.pos + rel

    def scalar(self, slot, fmt, default=None):
        p = self.field(slot)
        return self.number(fmt, p) if p is not None else default

    def indirect(self, slot):
        p = self.field(slot)
        return p + self.number("I", p) if p is not None else None

    def table(self, slot):
        p = self.indirect(slot)
        return Table(self.data, p) if p is not None else None

    def vector(self, slot, tables=False):
        p = self.indirect(slot)
        if p is None:
            return [] if tables else b""
        count = self.number("I", p)
        self.bounds(p + 4, count * (4 if tables else 1))
        if tables:
            return [Table(self.data, p + 4 + 4 * i + self.number("I", p + 4 + 4 * i)) for i in range(count)]
        return self.data[p + 4:p + 4 + count]

    def string(self, slot):
        return self.vector(slot).decode("utf-8")

    def pair(self, slot):
        p = self.field(slot)
        if p is None:
            raise ValueError("Missing coordinate field")
        self.bounds(p, 8)
        return struct.unpack_from("<2f", self.data, p)

    def ids(self, slot, count=3, vector=False):
        p = self.indirect(slot) if vector else self.field(slot)
        if p is None:
            return [] if vector else None
        n = self.number("I", p) if vector else 1
        p += 4 if vector else 0
        self.bounds(p, n * count * 4)
        values = [tuple(struct.unpack_from("<" + "I" * count, self.data, p + i * count * 4)) for i in range(n)]
        return values if vector else values[0]


def key(value):
    return ":".join(map(str, value)) if value is not None else None


def asset_info(table):
    p = table.field(0)
    if p is None:
        raise ValueError("Missing asset hash")
    table.bounds(p, 64)
    return {"id": table.data[p:p + 64].hex(), "filename": table.string(1), "mime": table.string(2)}


def recording_timeline(strokes, recordings):
    """Epoch links are derived, not independently verified native Note Replay links."""
    timeline = []
    for s in strokes:
        raw = s["raw_timestamp_fields"]
        start, end = raw.get("3"), raw.get("2")
        if start is None or end is None or end < start:
            continue
        hits = [r for r in recordings if r["start_ms"] <= start <= end <= r["end_ms"]]
        if len(hits) != 1:
            continue
        r = hits[0]
        timeline.append({"stroke_id": s["id"], "page_id": s.get("page_id"),
                         "page_number": s.get("page_number"), "recording_id": r["id"],
                         "start": (start - r["start_ms"]) / 1000, "end": (end - r["start_ms"]) / 1000,
                         "basis": "derived_epoch_interval", "status": "candidate",
                         "native_replay_verified": False})
    return timeline


def modern_stroke(payload, sid):
    ox, oy = payload.pair(1)
    blob = payload.vector(9)
    if len(blob) < 14:
        raise ValueError("Incomplete ink path")
    fmt, count = struct.unpack_from("<BH", blob)
    if fmt not in (0, 1) or count < 1:
        raise ValueError("Unrecognized ink path")
    coord = "f" if fmt else "e"
    size = 4 if fmt else 2
    offset = 12 if fmt else 8
    if len(blob) != offset + (count - 1) * (7 + 6 * size) + 6:
        raise ValueError("Ink fragments/erasure format not supported")
    points = [(ox, oy)]
    commands = [f"M {ox:g},{oy:g}"]
    for i in range(count - 1):
        pos = offset + i * (7 + 6 * size) + 7
        nums = struct.unpack_from("<6" + coord, blob, pos)
        coords = [(ox + nums[j], oy + nums[j + 1]) for j in (0, 2, 4)]
        points.extend(coords)
        commands.append("C " + " ".join(f"{x:g},{y:g}" for x, y in coords))
    colorpos = payload.field(7)
    if colorpos is None:
        rgba = [0, 0, 0, 255]
    else:
        payload.bounds(colorpos, 4)
        rgba = list(payload.data[colorpos:colorpos + 4])
    width = payload.scalar(8, "f", 1.0)
    return stroke(sid, points, " ".join(commands), width, rgba, geometry_status="untransformed_event")


def read_modern(data, exported):
    if len(data) < 8:
        raise ValueError("Truncated note blob")
    root = Table(data, struct.unpack_from("<I", data)[0])
    slot = 6 if exported else 0
    if root.field(slot) is None:
        raise ValueError("Unrecognized noteBundle/local persistence schema")
    ops = root.vector(slot, tables=True)
    note = blank("ntb" if exported else "local-flatbuffers")
    types = collections.Counter()
    skipped = collections.Counter()
    pages, page_order, deleted_pages, deleted_ops, recordings, ink_by_op = {}, [], set(), set(), [], {}
    default_size = (612.0, 792.0)
    order_supported = True
    for i, op in enumerate(ops):
        kind = op.scalar(4, "B", 0)
        types[str(kind)] += 1
        payload = op.table(5)
        if payload is None:
            continue
        if kind == 1:
            title = payload.table(0)
            if title:
                note["title"] = title.string(0)
            attrs = payload.table(1)
            if attrs and attrs.table(0) and attrs.table(0).field(3) is not None:
                default_size = attrs.table(0).pair(3)
        elif kind == 3:
            oid = op.ids(0, 2)
            if oid is None:
                order_supported = False
                continue
            count = payload.scalar(2, "I", 1)
            if not 1 <= count <= 10000 or len(pages) + count > 20000:
                raise ValueError("Unreasonable page count")
            template = payload.table(1)
            size = template.pair(3) if template and template.field(3) is not None else default_size
            if any(not math.isfinite(v) or not 0 < v < 10000 for v in size):
                raise ValueError("Invalid page dimensions")
            pdf = template.table(1) if template else None
            asset = asset_info(pdf.table(0)) if pdf and pdf.table(0) else None
            # Imported PDF attributes retain source dimensions; ink uses the document's normalized width.
            source_size = size
            if asset:
                size = (default_size[0], default_size[0] * size[1] / size[0])
            refs = [key((*oid, j)) for j in range(count)]
            for j, ref in enumerate(refs):
                if ref in pages:
                    raise ValueError("Duplicate page identifier")
                pages[ref] = {"id": ref, "width": size[0], "height": size[1], "source_dimensions": list(source_size),
                              "pdf": {**asset, "page": j + 1} if asset else None}
            anchor = key(payload.ids(0))
            if anchor is not None and anchor not in page_order:
                order_supported = False
            index = page_order.index(anchor) + 1 if anchor in page_order else 0
            page_order[index:index] = refs
        elif kind == 4:
            refs = [key(r) for r in payload.ids(0, vector=True)]
            target = payload.table(1)
            anchor = key(target.ids(0)) if target else None
            if any(r not in page_order for r in refs) or anchor in refs or (anchor is not None and anchor not in page_order):
                order_supported = False
                continue
            page_order = [r for r in page_order if r not in refs]
            index = page_order.index(anchor) + 1 if anchor in page_order else 0
            page_order[index:index] = refs
        elif kind == 5:
            holder = payload.table(0)
            asset = asset_info(holder.table(0)) if holder and holder.table(0) else None
            start, end = payload.scalar(1, "Q"), payload.scalar(2, "Q")
            if asset and start is not None and end is not None and end >= start:
                recordings.append({**asset, "start_ms": start, "end_ms": end,
                                   "duration_seconds": (end - start) / 1000, "operation_id": key(op.ids(0, 2))})
        elif kind == 15:
            try:
                s = modern_stroke(payload, f"op-{i}")
                s["raw_timestamp_fields"] = {str(j): op.scalar(j, "Q") for j in (1, 2, 3)}
                s["page_id"] = key(payload.ids(0))
                s["operation_id"] = key(op.ids(0, 2))
                note["strokes"].append(s)
                ink_by_op[s["operation_id"]] = s
            except (ValueError, struct.error) as exc:
                skipped[str(exc)] += 1
        elif kind == 24:
            for edit in payload.vector(0, tables=True):
                s = ink_by_op.get(key(edit.ids(0, 2)))
                transform = edit.table(3)
                if s is None or (transform and transform.scalar(0, "f", 0) != 0):
                    note["warnings"].append("Unsupported object transform; geometry may differ from the app")
                    continue
                ox, oy = map(float, s["path"].split()[1].split(","))
                nx, ny = edit.pair(2)
                dx, dy = nx - ox, ny - oy
                def shift(match):
                    x, y = map(float, match.group(0).split(","))
                    return f"{x + dx:g},{y + dy:g}"
                if not all(math.isfinite(v) and abs(v) < 1e7 for v in (nx, ny)):
                    raise ValueError("Invalid translated origin")
                s["path"] = re.sub(r"[-+\d.e]+,[-+\d.e]+", shift, s["path"])
                s["bounds"] = [s["bounds"][0] + dx, s["bounds"][1] + dy,
                               s["bounds"][2] + dx, s["bounds"][3] + dy]
                s["page_id"] = key(edit.ids(1))
                s["geometry_status"] = "translated_event"
        elif kind == 25:
            deleted_ops.update(key(r) for r in payload.ids(0, 2, True))
            deleted_ops.difference_update(key(r) for r in payload.ids(1, 2, True))
            deleted_pages.update(key(r) for r in payload.ids(2, 3, True))
            deleted_pages.difference_update(key(r) for r in payload.ids(3, 3, True))
    note["pages"] = [pages[r] for r in page_order if r not in deleted_pages]
    note["page_order_status"] = "derived_operation_order" if order_supported else "unresolved"
    for i, page in enumerate(note["pages"], 1):
        page["page_number"] = i if order_supported else None
    numbers = {p["id"]: p["page_number"] for p in note["pages"]}
    history_count = len(note["strokes"])
    note["strokes"] = [s for s in note["strokes"] if s["operation_id"] not in deleted_ops and s["page_id"] not in deleted_pages]
    for s in note["strokes"]:
        s["page_number"] = numbers.get(s["page_id"])
    note["discarded_stroke_count"] = history_count - len(note["strokes"])
    note["recordings"] = recordings
    note["timeline"] = recording_timeline(note["strokes"], recordings)
    note["op_types"] = dict(types)
    note["skipped_stroke_formats"] = dict(skipped)
    note["warnings"].append("Page order, PDF references, object deletes/restores and translations are derived from observed operations; pressure, rotation and fragment erasure are incomplete. Compare with official PDF")
    note["warnings"].append("Recording links use pen epoch minus recording-start epoch; native Note Replay, pauses/import playback clocks are not independently verified. Links are temporal candidates, not semantic proof")
    if types.get("8"):
        note["warnings"].append("Typed-text events exist but their current state/positions are not decoded")
    if skipped:
        note["warnings"].append(f"Skipped {sum(skipped.values())} unsupported ink events; see skipped_stroke_formats")
    return note
