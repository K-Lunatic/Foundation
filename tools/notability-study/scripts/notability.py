#!/usr/bin/env python3
"""Read Notability notes and ASR caches; prepare grounded inputs for a study skill."""
import argparse
import collections
import datetime
import hashlib
import html
import json
import math
import pathlib
import plistlib
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
import unicodedata
import uuid
import zipfile

from note_formats import read_legacy, read_modern

STORE = pathlib.Path.home() / "Library/Containers/com.gingerlabs.Notability/Data/Library/Application Support/local-persistence-collab-production"
MAX_ENTRY = 128 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024


def stable_read(path):
    before = path.stat()
    if before.st_size > MAX_ENTRY:
        raise ValueError(f"Note/cache too large to parse: {path.name}")
    data = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Source changed during read; retry after it finishes saving")
    return data


def identifier(value):
    return str(uuid.UUID(bytes=value)).upper() if isinstance(value, bytes) else str(uuid.UUID(str(value))).upper()


def database(store):
    path = (store / "local_persistence").resolve()
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def list_notes(store):
    with database(store) as conn:
        rows = conn.execute("SELECT id,title,modified,hasRecordings,isDownloaded FROM note_metadata WHERE deleted IS NULL ORDER BY modified DESC").fetchall()
    return [{"note_id": identifier(r["id"]), "title": r["title"], "modified": r["modified"],
             "has_recordings": bool(r["hasRecordings"]), "downloaded": bool(r["isDownloaded"])} for r in rows]


def signature(path):
    with path.open("rb") as f:
        head = f.read(32)
    if head.startswith(b"%PDF-"):
        return ".pdf", "pdf"
    if head.startswith(b"\x89PNG"):
        return ".png", "image"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image"
    if head[4:8] == b"ftyp":
        return (".m4a", "audio") if head[8:12] == b"M4A " else (".mp4", "video")
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 255 and head[1] & 0xE0 == 0xE0):
        return ".mp3", "audio"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return ".wav", "audio"
    return ".bin", "unknown"


def copy_media(source, output, name):
    before = source.stat()
    if before.st_size > MAX_TOTAL:
        raise ValueError("Media file exceeds 2 GiB limit")
    suffix, kind = signature(source)
    dest = output / "media" / (name + suffix)
    dest.parent.mkdir(exist_ok=True)
    shutil.copyfile(source, dest)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Media changed while copying; retry after recording stops")
    return {"id": name, "kind": kind, "path": dest.relative_to(output).as_posix()}


def normalize_segments(rows, recording_id, origin):
    result = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Transcript segments must be objects")
        start = row.get("start", row.get("startTime"))
        end = row.get("end", row.get("endTime"))
        timed = start is not None or end is not None
        if timed:
            if start is None or end is None:
                raise ValueError("Both start and end timestamps are required")
            start, end = float(start), float(end)
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                raise ValueError("Invalid transcript timestamps (seconds required)")
        text = row.get("text")
        if not isinstance(text, str):
            raise ValueError("Transcript text must be a string")
        if text.strip():
            result.append({"id": f"{recording_id}:{i}", "recording_id": recording_id,
                           "start": start, "end": end, "text": text,
                           "confidence": row.get("confidence"), "origin": origin})
    return result


def clock_seconds(value):
    parts = value.replace(",", ".").split(":")
    if len(parts) not in (2, 3):
        raise ValueError("Invalid subtitle timestamp")
    seconds = float(parts[-1])
    minutes = int(parts[-2])
    hours = int(parts[0]) if len(parts) == 3 else 0
    if hours < 0 or minutes < 0 or (len(parts) == 3 and minutes >= 60) or not 0 <= seconds < 60:
        raise ValueError("Invalid subtitle timestamp")
    return hours * 3600 + minutes * 60 + seconds


def read_transcript(path, recording_id):
    if path.suffix.lower() == ".plist":
        data = plistlib.loads(stable_read(path))
        rows = data["segments"]
    elif path.suffix.lower() == ".json":
        data = json.loads(stable_read(path))
        rows = data if isinstance(data, list) else data["segments"]
    elif path.suffix.lower() in (".srt", ".vtt"):
        text = stable_read(path).decode("utf-8-sig").replace("\r\n", "\n")
        rows = []
        for block in re.split(r"\n\s*\n", text):
            lines = block.splitlines()
            for i, line in enumerate(lines):
                if "-->" in line:
                    a, b = line.split("-->", 1)
                    rows.append({"start": clock_seconds(a.strip()), "end": clock_seconds(b.strip().split()[0]),
                                 "text": "\n".join(lines[i + 1:])})
                    break
        if not rows:
            raise ValueError("No valid subtitle cues found")
    elif path.suffix.lower() == ".txt":
        rows = [{"text": stable_read(path).decode("utf-8-sig")}]
    else:
        raise ValueError("Transcript must be .plist, .json, .srt, .vtt or .txt")
    if not isinstance(rows, list):
        raise ValueError("Transcript segments must be a list")
    return normalize_segments(rows, recording_id, str(path.resolve()))


def extract_local(store, note_id, output):
    note_id = identifier(note_id)
    with database(store) as conn:
        conn.execute("BEGIN")
        rows = conn.execute("SELECT id,userId,title,modified FROM note_metadata WHERE deleted IS NULL").fetchall()
        hits = [r for r in rows if identifier(r["id"]) == note_id]
        if len(hits) != 1:
            raise ValueError("Note ID must identify one live local note")
        row = hits[0]
        assets = conn.execute("SELECT assetHash FROM asset_note_associations WHERE noteId=? AND userId=?", (row["id"], row["userId"])).fetchall()
        legacy = conn.execute("SELECT hash FROM legacy_note_recording_association WHERE noteId=? COLLATE NOCASE", (note_id,)).fetchall()
    blob = store / "notes" / note_id
    if not blob.exists():
        raise ValueError("Note is not downloaded locally; open it in Notability first")
    raw = stable_read(blob)
    note = read_modern(raw, exported=False)
    note.update(note_id=note_id, title=row["title"] or note_id, modified=row["modified"], source=str(blob))
    note["source_sha256"] = hashlib.sha256(raw).hexdigest()
    hashes = sorted({a[0] for a in assets} | {a[0] for a in legacy})
    for asset_hash in hashes:
        if not re.fullmatch(r"[a-fA-F0-9]{128}", asset_hash):
            note["warnings"].append("Unrecognized asset hash skipped")
            continue
        asset = store / "assets" / asset_hash
        if asset.is_file():
            item = copy_media(asset, output, asset_hash)
            note["media"].append(item)
        cache = store / "asr" / (asset_hash.lower() + ".plist")
        if cache.is_file():
            note["segments"].extend(read_transcript(cache, asset_hash))
    if not note["segments"]:
        note["warnings"].append("No completed transcript cache linked to this note")
    return note


def extract_bundle(path, output):
    if path.is_dir():
        paths = [p for p in path.rglob("*") if p.is_file()]
        if any(p.is_symlink() or not p.resolve().is_relative_to(path.resolve()) for p in paths):
            raise ValueError("Symlink outside note package")
        members = {p.relative_to(path).as_posix(): p for p in paths}
        reader = lambda name: stable_read(members[name])
        return bundle_contents(members, reader, output)
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > MAX_TOTAL:
            raise ValueError("Archive exceeds size/count limits")
        names = [i.filename for i in infos if not i.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive members")
        for name in names:
            p = pathlib.PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name:
                raise ValueError("Unsafe archive member")
        def reader(name):
            if archive.getinfo(name).file_size > MAX_ENTRY:
                raise ValueError("Archive entry too large")
            return archive.read(name)
        return bundle_contents(names, reader, output)


def bundle_contents(members, reader, output):
    sessions = [n for n in members if pathlib.PurePosixPath(n).name == "Session.plist"]
    if "noteBundle" in members:
        note = read_modern(reader("noteBundle"), exported=True)
    elif len(sessions) == 1:
        note = read_legacy(plistlib.loads(reader(sessions[0])))
    else:
        raise ValueError("Expected one Session.plist or a noteBundle; unsupported package")
    for name in members:
        suffix = pathlib.PurePosixPath(name).suffix.lower()
        if suffix in (".m4a", ".mp3", ".mp4", ".wav", ".pdf", ".png", ".jpg", ".jpeg"):
            dest = output / "media" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(reader(name))
            _, kind = signature(dest)
            note["media"].append({"id": name, "kind": kind, "path": dest.relative_to(output).as_posix()})
    # Archive member order is not significant; map recordings after all media are copied.
    for name in members:
        if pathlib.PurePosixPath(name).name == "library.plist":
            for r in plistlib.loads(reader(name)).get("recordings", {}).values():
                if isinstance(r, dict) and "identifier" in r and "filepath" in r:
                    source = (pathlib.PurePosixPath(name).parent / r["filepath"]).as_posix()
                    for item in note["media"]:
                        if item["id"] == source:
                            item["recording_id"] = str(r["identifier"])
    return note


def temporal_candidates(note):
    by_recording = collections.defaultdict(list)
    for event in note["timeline"]:
        by_recording[str(event["recording_id"])].append(event)
    candidates = []
    for seg in note["segments"]:
        if seg["start"] is None:
            continue
        ids = sorted({e["stroke_id"] for e in by_recording[seg["recording_id"]]
                      if e["start"] < seg["end"] and e["end"] >= seg["start"]})
        if ids:
            candidates.append({"segment_id": seg["id"], "stroke_ids": ids, "basis": "recording_timeline_overlap", "semantic_match": False})
    return candidates


def validate_recording_clocks(note, output):
    """Reject wall-clock intervals inconsistent with the actual saved audio duration."""
    media = {m["id"]: m for m in note["media"] if m["kind"] == "audio"}
    probe = shutil.which("afinfo")
    for r in note.get("recordings", []):
        r["clock_status"] = "unverified"
        if not probe or r["id"] not in media:
            continue
        try:
            result = subprocess.run([probe, str(output / media[r["id"]]["path"])],
                                    capture_output=True, text=True, timeout=15, check=True)
            match = re.search(r"estimated duration:\s*([\d.]+)\s*sec", result.stdout)
            if match:
                duration = float(match.group(1))
                r["media_duration_seconds"] = duration
                r["duration_difference_seconds"] = duration - r["duration_seconds"]
                r["clock_status"] = "duration_consistent" if abs(r["duration_difference_seconds"]) < 1 else "duration_mismatch"
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    status = {r["id"]: r["clock_status"] for r in note.get("recordings", [])}
    note["timeline"] = [e for e in note["timeline"] if status.get(e["recording_id"]) != "duration_mismatch"]
    for event in note["timeline"]:
        event["clock_validation"] = status.get(event["recording_id"], "legacy_uuid")
    linked = {e["stroke_id"] for e in note["timeline"]}
    note["unmatched_stroke_ids"] = [s["id"] for s in note["strokes"] if s["id"] not in linked]
    if "duration_mismatch" in status.values():
        note["warnings"].append("Recording duration differs from epoch interval; corresponding wall-clock links were discarded")


def write_ink_preview(note, output, background=None):
    strokes = note["strokes"]
    boxes = [s["bounds"] for s in strokes]
    if not boxes:
        return
    if "width" in note:
        x, y, w, h = 0, 0, note["width"], note["height"]
    else:
        x = min(b[0] for b in boxes) - 10
        y = min(b[1] for b in boxes) - 10
        w = max(b[2] for b in boxes) - x + 10
        h = max(b[3] for b in boxes) - y + 10
    paths = []
    for s in strokes:
        r, g, b, a = s["rgba"]
        paths.append(f'<path id="{html.escape(s["id"], quote=True)}" d="{s["path"]}" fill="none" stroke="rgb({r},{g},{b})" stroke-opacity="{a / 255}" stroke-width="{s["width"]}" stroke-linecap="round" stroke-linejoin="round"><title>{html.escape(s["id"])}</title></path>')
    backdrop = f'<image href="{html.escape(background.name,quote=True)}" width="{w}" height="{h}"/>' if background else ''
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {max(w,1)} {max(h,1)}">' + backdrop + "".join(paths) + "</svg>"
    (output / "ink.svg").write_text(svg, encoding="utf-8")
    note["preview_bounds"] = [x, y, max(w, 1), max(h, 1)]
    # Use Pillow only if already installed; the extractor itself remains standard-library only.
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    scale = min(1800 / max(w, 1), 1800 / max(h, 1))
    dimensions = (max(1, math.ceil(w * scale)), max(1, math.ceil(h * scale)))
    image = Image.open(background).convert("RGB").resize(dimensions) if background else Image.new("RGB", dimensions, "white")
    draw = ImageDraw.Draw(image)
    for s in strokes:
        tokens = re.findall(r"[MLC]|[-+]?\d*\.?\d+(?:e[-+]?\d+)?", s["path"])
        points, cursor = [], 0
        current = (0, 0)
        while cursor < len(tokens):
            command = tokens[cursor]
            count = 6 if command == "C" else 2
            nums = [float(v) for v in tokens[cursor + 1:cursor + 1 + count]]
            cursor += 1 + count
            if command == "C":
                start = current
                for j in range(1, 17):
                    t, u = j / 16, 1 - j / 16
                    points.append((u**3 * start[0] + 3 * u*u*t * nums[0] + 3 * u*t*t * nums[2] + t**3 * nums[4],
                                   u**3 * start[1] + 3 * u*u*t * nums[1] + 3 * u*t*t * nums[3] + t**3 * nums[5]))
                current = (nums[4], nums[5])
            else:
                current = (nums[0], nums[1])
                points.append(current)
        a = s["rgba"][3] / 255
        rgb = tuple(round(c * a + 255 * (1 - a)) for c in s["rgba"][:3])
        draw.line([((px - x) * scale, (py - y) * scale) for px, py in points], fill=rgb,
                  width=max(1, round(s["width"] * scale)))
    image.save(output / "ink.png")


def write_preview(note, output):
    pages = note.get("pages", [])
    if not pages:
        # shortcut: legacy page framing remains unknown; preserve its explicitly unpaged preview.
        write_ink_preview(note, output)
        return
    media = {m["id"]: m for m in note["media"] if m["kind"] == "pdf"}
    renderer = shutil.which("pdftoppm")
    for page in pages:
        strokes = [s for s in note["strokes"] if s.get("page_id") == page["id"]]
        page["stroke_ids"] = [s["id"] for s in strokes]
        if not strokes:
            continue
        dest = output / "pages" / ("page-" + page["id"].replace(":", "-"))
        dest.mkdir(parents=True)
        background = None
        pdf = page.get("pdf")
        if renderer and pdf and pdf["id"] in media:
            try:
                subprocess.run([renderer, "-f", str(pdf["page"]), "-l", str(pdf["page"]), "-singlefile",
                                "-scale-to", "1440", "-png", str(output / media[pdf["id"]]["path"]), str(dest / "background")],
                               capture_output=True, timeout=30, check=True)
                background = dest / "background.png"
            except (OSError, subprocess.SubprocessError):
                note["warnings"].append(f"Could not render PDF background for page {page['id']}")
        preview = {**page, "strokes": strokes}
        write_ink_preview(preview, dest, background)
        page["preview"] = {"svg": (dest / "ink.svg").relative_to(output).as_posix(),
                           "bounds": preview["preview_bounds"], "background_rendered": bool(background)}
        if (dest / "ink.png").exists():
            page["preview"]["png"] = (dest / "ink.png").relative_to(output).as_posix()
    known = {p["id"] for p in pages}
    unknown = [s for s in note["strokes"] if s.get("page_id") not in known]
    if unknown:
        dest = output / "pages" / "unresolved"
        dest.mkdir(parents=True)
        write_ink_preview({"strokes": unknown}, dest)
        note["warnings"].append(f"{len(unknown)} strokes have unresolved page references; isolated in pages/unresolved")


def write_review(note, output):
    esc = html.escape
    sections = []
    media_by_id = {m.get("recording_id", m["id"]): m for m in note["media"] if m["kind"] in ("audio", "video")}
    for recording_id in dict.fromkeys(s["recording_id"] for s in note["segments"]):
        media = media_by_id.get(recording_id)
        player_id = "p" + hashlib.sha256(recording_id.encode()).hexdigest()[:12]
        player = f'<audio id="{player_id}" controls preload="none" src="{esc(media["path"],quote=True)}"></audio>' if media else "<p>이 전사 구간에 연결된 오디오 파일이 없습니다.</p>"
        cues = []
        for seg in note["segments"]:
            if seg["recording_id"] != recording_id:
                continue
            label = f'{seg["start"]:.2f}s' if seg["start"] is not None else "시간 없음"
            button = f'<button data-player="{player_id}" data-time="{seg["start"]}">{label}</button>' if media and seg["start"] is not None else esc(label)
            cues.append(f'<p>{button} <span>{esc(seg["text"])}</span></p>')
        sections.append(player + "".join(cues))
    warnings = "".join(f"<li>{esc(w)}</li>" for w in note["warnings"])
    ink = '<a href="ink.svg" target="_blank">페이지 미확인 필기 미리보기</a>' if (output / "ink.svg").exists() else "페이지별 필기 미리보기"
    pdfs = " ".join(f'<a href="{esc(m["path"],quote=True)}">PDF 원본 {i + 1}</a>' for i, m in enumerate(note["media"]) if m["kind"] == "pdf")
    doc = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Notability 검토</title><style>body{font:16px system-ui;max-width:1000px;margin:32px auto;padding:16px;line-height:1.7}audio{width:100%}button{cursor:pointer;padding:6px}li{color:#654}span{white-space:pre-wrap}</style>'
    doc += f'<h1>{esc(note["title"])}</h1><p>{ink} {pdfs}</p><details open><summary>추출 상태와 제한</summary><ul>{warnings}</ul></details>'
    for page in note.get("pages", []):
        if "preview" not in page:
            continue
        number = page.get("page_number") or page["id"]
        preview = page["preview"]
        doc += f'<h2>페이지 {esc(str(number))}</h2><a href="{esc(preview["svg"],quote=True)}">페이지 필기 확대</a>'
        if "png" in preview:
            doc += f'<img src="{esc(preview["png"],quote=True)}" alt="페이지 {esc(str(number))}의 분리된 필기" style="width:100%">'
        for event in note["timeline"]:
            if event.get("page_id") != page["id"]:
                continue
            rid = event["recording_id"]
            if rid in media_by_id and any(s["recording_id"] == rid for s in note["segments"]):
                pid = "p" + hashlib.sha256(rid.encode()).hexdigest()[:12]
                doc += f'<button data-player="{pid}" data-time="{event["start"]}">{esc(event["stroke_id"])} · {event["start"]:.2f}s</button> '
    if (output / "ink.png").is_file():
        doc += '<details><summary>필기 획 미리보기</summary><img src="ink.png" alt="추출된 필기 획. 최신 형식은 편집 이력을 포함할 수 있음" style="max-width:100%"></details>'
    doc += "".join(sections) or "<p>전사본이 없습니다. 외부 SRT/VTT/JSON 전사를 함께 지정할 수 있습니다.</p>"
    doc += '<script>document.addEventListener("click",e=>{const b=e.target.closest("button[data-time]");if(!b)return;const a=document.getElementById(b.dataset.player);a.currentTime=Number(b.dataset.time);a.play().catch(()=>{});});</script></html>'
    (output / "review.html").write_text(doc, encoding="utf-8")


def match_concepts(note, regions):
    """Rank transcript evidence for concepts read from ink/PDF by the skill."""
    strokes = {s["id"] for s in note["strokes"]}
    seen = set()
    matches = []
    def normalized(text):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())
    for region in regions:
        if not isinstance(region, dict) or not isinstance(region.get("id"), str) or region["id"] in seen:
            raise ValueError("Regions require unique string IDs")
        seen.add(region["id"])
        if not isinstance(region.get("concept"), str) or not isinstance(region.get("evidence"), str) or not region["evidence"].strip():
            raise ValueError("Each concept needs a written/visual evidence description")
        ids = region.get("stroke_ids", [])
        if not isinstance(ids, list) or not ids or any(s not in strokes for s in ids):
            raise ValueError("Each region must reference extracted stroke IDs")
        terms = region.get("keywords", [region["concept"]])
        if not isinstance(terms, list) or not terms or any(not isinstance(t, str) or not t.strip() for t in terms):
            raise ValueError("Keywords must be nonempty strings")
        terms = list(dict.fromkeys(terms))
        region_events = [e for e in note["timeline"] if e["stroke_id"] in ids]
        page_ids = sorted({s.get("page_id") for s in note["strokes"] if s["id"] in ids and s.get("page_id")})
        if len(page_ids) > 1:
            raise ValueError("A concept region must belong to one page; split cross-page regions")
        ranked = []
        for seg in note["segments"]:
            found = [t for t in terms if normalized(t) in normalized(seg["text"])]
            overlap = [e["stroke_id"] for e in region_events if e["recording_id"] == seg["recording_id"] and
                       seg["start"] is not None and e["start"] < seg["end"] and e["end"] >= seg["start"]]
            if found or overlap:
                same_clock = [e for e in region_events if e["recording_id"] == seg["recording_id"]]
                distance = min((max(e["start"] - seg["end"], seg["start"] - e["end"], 0) for e in same_clock), default=None) if seg["start"] is not None else None
                ranked.append({"segment_id": seg["id"], "recording_id": seg["recording_id"],
                               "start": seg["start"], "end": seg["end"], "text": seg["text"],
                               "matched_keywords": found, "score": len(found) / len(terms),
                               "overlapping_stroke_ids": overlap, "temporal_overlap": bool(overlap),
                               "same_recording": bool(same_clock), "distance_seconds": distance,
                               "status": "candidate", "basis": "timeline_and_keyword" if found and overlap else "timeline_overlap" if overlap else "keyword_evidence"})
        ranked.sort(key=lambda s: (-bool(s["temporal_overlap"]), -bool(s["same_recording"]), -s["score"],
                                   s["distance_seconds"] if s["distance_seconds"] is not None else float("inf")))
        matches.append({"region_id": region["id"], "concept": region["concept"], "stroke_ids": ids,
                        "evidence": region["evidence"], "page_ids": page_ids,
                        "writing_intervals": region_events, "candidates": ranked[:5]})
    return matches


def align(output, annotations):
    note = json.loads(stable_read(output / "note.json"))
    regions = json.loads(stable_read(annotations))
    if not isinstance(regions, list):
        raise ValueError("Annotations must be a JSON list of regions")
    matches = match_concepts(note, regions)
    if any((output / name).exists() for name in ("matches.json", "concepts.html")):
        raise ValueError("Alignment outputs already exist; use a fresh extract directory to preserve earlier work")
    (output / "matches.json").write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    esc = html.escape
    players = {m.get("recording_id", m["id"]): m for m in note["media"] if m["kind"] in ("audio", "video")}
    body = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>개념과 강의 연결</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px;line-height:1.7}button{padding:8px;cursor:pointer}audio{width:100%}.ink{width:100%;height:600px;border:1px solid #ccc}blockquote{border-left:3px solid #ccc;padding:12px}</style><h1>개념과 강의 연결 후보</h1><p>시간이 겹치는 전사를 먼저 제시하고 키워드 후보를 별도로 표시합니다. 같은 개념인지 문맥을 확인하세요. 녹음 시계와 편집 복원 제한은 note.json에 있습니다.</p>'
    if (output / "ink.svg").is_file():
        body += '<iframe class="ink" src="ink.svg" title="필기 획 미리보기"></iframe>'
    body += '<audio id="player" controls preload="none"></audio>'
    for match in matches:
        body += f'<h2>{esc(match["concept"])}</h2><p>필기 근거: {esc(match["evidence"])}</p>'
        for page in note.get("pages", []):
            if page["id"] in match["page_ids"] and "preview" in page:
                body += f'<p>페이지 {page.get("page_number") or esc(page["id"])}</p><iframe class="ink" src="{esc(page["preview"]["svg"],quote=True)}" title="분리된 페이지"></iframe>'
        for rid in dict.fromkeys(e["recording_id"] for e in match["writing_intervals"]):
            events = [e for e in match["writing_intervals"] if e["recording_id"] == rid]
            start, end = min(e["start"] for e in events), max(e["end"] for e in events)
            media = players.get(rid)
            button = f'<button data-src="{esc(media["path"],quote=True)}" data-time="{start}">작성 시각 듣기</button>' if media else ''
            body += f'<p>{button} 녹음 {esc(rid[:8])} · 작성 시각(추정) {start:.3f}–{end:.3f}s. 의미상 설명 시각과 다를 수 있습니다.</p>'
        for cue in match["candidates"]:
            media = players.get(cue["recording_id"])
            button = ''
            if media and cue["start"] is not None:
                button = f'<button data-src="{esc(media["path"],quote=True)}" data-time="{cue["start"]}">{cue["start"]:.2f}초 듣기</button>'
            body += f'<blockquote>{button}<p>{esc(cue["text"])}</p><small>녹음 {esc(cue["recording_id"][:8])} · 근거: {esc(cue["basis"])} · 일치 키워드: {esc(", ".join(cue["matched_keywords"]))}</small></blockquote>'
        if not match["candidates"]:
            body += '<p>근거 있는 연결 후보를 찾지 못했습니다.</p>'
    body += '<script>document.addEventListener("click",e=>{const b=e.target.closest("button[data-src]");if(!b)return;const a=document.getElementById("player");const seek=()=>{a.currentTime=Number(b.dataset.time);a.play().catch(()=>{});};if(a.getAttribute("src")!==b.dataset.src){a.src=b.dataset.src;a.addEventListener("loadedmetadata",seek,{once:true});}else seek();});</script></html>'
    (output / "concepts.html").write_text(body, encoding="utf-8")
    return {"output": str(output / "concepts.html"), "concepts": len(matches),
            "with_candidates": sum(bool(m["candidates"]) for m in matches)}


def extract(args, output):
    source = (args.store if args.note_id else args.input).resolve()
    out = output.resolve()
    if out == source or out.is_relative_to(source) or source.is_relative_to(out):
        raise ValueError("Output must be separate from the Notability source")
    out.mkdir(parents=True, exist_ok=False)
    note = extract_local(args.store, args.note_id, out) if args.note_id else extract_bundle(args.input, out)
    note.setdefault("source", str(source))
    note.setdefault("title", args.input.stem if args.input else args.note_id)
    note["schema_version"] = 2
    note["captured_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if args.audio:
        note["media"].append(copy_media(args.audio, out, "external"))
    if args.transcript:
        # External audio is a separate clock; never attach it to native ink timestamps implicitly.
        rid = args.recording_id or "external"
        if args.audio and rid != "external":
            note["media"][-1]["recording_id"] = rid
        note["segments"].extend(read_transcript(args.transcript, rid))
    validate_recording_clocks(note, out)
    note["temporal_candidates"] = temporal_candidates(note)
    write_preview(note, out)
    write_review(note, out)
    (out / "note.json").write_text(json.dumps(note, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return {"output": str(out), "strokes": len(note["strokes"]), "segments": len(note["segments"]),
            "audio_files": sum(m["kind"] == "audio" for m in note["media"]), "timeline_links": len(note["temporal_candidates"]),
            "warnings": note["warnings"]}


def watch_fingerprint(args):
    note_id = identifier(args.note_id)
    with database(args.store) as conn:
        conn.execute("BEGIN")
        rows = conn.execute("SELECT id,userId,modified FROM note_metadata WHERE deleted IS NULL").fetchall()
        row = next((r for r in rows if identifier(r["id"]) == note_id), None)
        if row is None:
            raise ValueError("Note is no longer available")
        hashes = conn.execute("SELECT assetHash FROM asset_note_associations WHERE noteId=? AND userId=?", (row["id"], row["userId"])).fetchall()
        hashes += conn.execute("SELECT hash FROM legacy_note_recording_association WHERE noteId=? COLLATE NOCASE", (note_id,)).fetchall()
    source = args.store / "notes" / note_id
    paths = [source]
    for (h,) in hashes:
        if re.fullmatch(r"[a-fA-F0-9]{128}", h):
            paths += [args.store / "assets" / h, args.store / "asr" / (h.lower() + ".plist")]
    paths += [p for p in (args.audio, args.transcript) if p]
    return (row["modified"], tuple(sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths if p.exists())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "extract", "watch", "align"))
    parser.add_argument("--store", type=pathlib.Path, default=STORE)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--note-id")
    group.add_argument("--input", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--audio", type=pathlib.Path)
    parser.add_argument("--transcript", type=pathlib.Path)
    parser.add_argument("--recording-id", help="Only use native IDs when transcript belongs to that exact native recording")
    parser.add_argument("--annotations", type=pathlib.Path, help="Ink regions/concepts read by the skill")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--interval", type=float, default=3)
    args = parser.parse_args()
    if args.command == "list":
        if args.limit < 1:
            parser.error("--limit must be positive")
        print(json.dumps(list_notes(args.store)[:args.limit], ensure_ascii=False, indent=2))
        return
    if args.command == "align":
        if not args.output or not args.annotations:
            parser.error("align requires --output and --annotations")
        if args.output.resolve().is_relative_to(args.store.resolve()):
            parser.error("align output must be outside the source store")
        print(json.dumps(align(args.output, args.annotations), ensure_ascii=False))
        return
    if not (args.input or args.note_id) or not args.output:
        parser.error("extract/watch require --note-id or --input and --output")
    if args.command == "extract":
        print(json.dumps(extract(args, args.output), ensure_ascii=False))
        return
    if not args.note_id:
        parser.error("watch currently requires --note-id")
    if not math.isfinite(args.interval) or args.interval < 1:
        parser.error("--interval must be at least one second")
    if args.output.resolve().is_relative_to(args.store.resolve()):
        parser.error("watch output must be outside the source store")
    fingerprint = None
    while True:
        try:
            current = watch_fingerprint(args)
            if current != fingerprint:
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
                dest = args.output / (stamp + "-" + uuid.uuid4().hex[:8])
                print(json.dumps(extract(args, dest), ensure_ascii=False), flush=True)
                fingerprint = current
        except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
            print(json.dumps({"retrying": True, "error": str(exc)}), file=sys.stderr, flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, KeyError, sqlite3.Error, zipfile.BadZipFile, plistlib.InvalidFileException, struct.error) as exc:
        print(f"Notability extraction failed: {exc}", file=sys.stderr)
        sys.exit(1)
