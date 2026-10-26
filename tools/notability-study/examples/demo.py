"""Synthetic post-extraction matching demo; contains no real note or audio."""
import argparse
import json
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from notability import align

def fixtures():
    note = {
        "strokes": [{"id": "synthetic-1", "page_id": "demo-page"}],
        "timeline": [{"stroke_id": "synthetic-1", "recording_id": "demo-a", "start": 10, "end": 12}],
        "segments": [
            {"id": "other-clock", "recording_id": "demo-b", "start": 10, "end": 14, "text": "큐는 먼저 들어온 항목을 먼저 꺼냅니다."},
            {"id": "same-clock", "recording_id": "demo-a", "start": 9, "end": 14, "text": "큐는 먼저 들어온 항목을 먼저 꺼냅니다."}
        ],
        "media": [], "pages": [],
        "warnings": ["Synthetic post-extraction data. No native note parsing or audio."],
    }
    regions = [{"id": "region-1", "concept": "큐", "keywords": ["큐"],
                "stroke_ids": ["synthetic-1"], "evidence": "가상 예시: 큐의 FIFO 설명을 지정했다고 가정합니다."}]
    return note, regions

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    note, regions = fixtures()
    (args.output / "note.json").write_text(json.dumps(note, ensure_ascii=False), encoding="utf-8")
    annotations = args.output / "regions.json"
    annotations.write_text(json.dumps(regions, ensure_ascii=False), encoding="utf-8")
    result = align(args.output, annotations)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
