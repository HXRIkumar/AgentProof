#!/usr/bin/env python3
"""Freeze a reproducible public SQuAD v2 subset; this does not invoke any model."""

import argparse
import hashlib
import json
from pathlib import Path

UPSTREAM_URL = "https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v2.0.json"
SEED = 20261112


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def rank(value):
    return hashlib.sha256(f"{SEED}:{value}".encode()).hexdigest()


def select_qa(document):
    """Select once per paragraph, balance answerability and cycle through topics."""
    buckets = {True: {}, False: {}}
    for article in document["data"]:
        for paragraph in article["paragraphs"]:
            context = paragraph["context"]
            # Keep per-request contexts small enough for a laptop; disclosed selection filter.
            if not 150 <= len(context) <= 2400:
                continue
            for qa in paragraph["qas"]:
                label = not qa.get("is_impossible", False)
                if label and not qa["answers"]:
                    continue
                buckets[label].setdefault(article["title"], []).append((context, qa))
    for groups in buckets.values():
        for title, rows in groups.items():
            groups[title] = sorted(rows, key=lambda row: rank(row[1]["id"]))
    used_context = set()
    selections = {True: [], False: []}
    for label in (True, False):
        titles = sorted(buckets[label], key=rank)
        while len(selections[label]) < 30:
            progress = False
            for title in titles:
                rows = buckets[label][title]
                while rows and fingerprint(rows[0][0]) in used_context:
                    rows.pop(0)
                if rows:
                    context, qa = rows.pop(0)
                    used_context.add(fingerprint(context))
                    selections[label].append((title, context, qa))
                    progress = True
                if len(selections[label]) == 30:
                    break
            if not progress:
                raise ValueError("Insufficient distinct paragraphs for balanced freeze")
    result = {"development": [], "evaluation": []}
    for label in (True, False):
        for index, (title, context, qa) in enumerate(selections[label]):
            split = "development" if index < 6 else "evaluation"
            result[split].append({
                "id": f"squad2-{qa['id']}", "task": "qa",
                "category": "answerable" if label else "unanswerable",
                "origin": {"dataset": "SQuAD v2.0 dev", "question_id": qa["id"],
                           "title": title, "license": "CC BY-SA 4.0"},
                "request": {"question": qa["question"], "task": "qa", "sources": [
                    {"id": "passage", "title": title.replace("_", " "), "text": context}
                ]},
                "gold": {"answers": sorted({a["text"] for a in qa["answers"]}),
                         "answerable": label},
            })
    for cases in result.values():
        cases.sort(key=lambda case: rank(case["id"]))
    distractors = []
    for article in document["data"]:
        for paragraph in article["paragraphs"]:
            context = paragraph["context"]
            if 150 <= len(context) <= 650 and fingerprint(context) not in used_context:
                distractors.append((article["title"], context))
    distractors.sort(key=lambda pair: rank(fingerprint(pair)))
    for cases in result.values():
        for case in cases:
            original = case["request"]["sources"][0]
            selected = [original]
            for title, context in distractors:
                if title == case["origin"]["title"]:
                    continue
                if any(a.lower() in context.lower() for a in case["gold"]["answers"]):
                    continue
                if any(source["title"] == title for source in selected):
                    continue
                selected.append({"id": "", "title": title.replace("_", " "), "text": context})
                if len(selected) == 3:
                    break
            if len(selected) != 3:
                raise ValueError("Unable to find two distinct distractor paragraphs")
            selected.sort(key=lambda source: rank(case["id"] + source["text"]))
            for i, source in enumerate(selected):
                source["id"] = f"source-{i + 1}"
                if source is original:
                    case["gold"]["relevant_source_ids"] = [source["id"]]
            case["request"]["sources"] = selected
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.upstream.read_bytes()
    document = json.loads(raw)
    qa = select_qa(document)
    authored = json.loads(args.extraction.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "version": "answer-suite-v1", "seed": SEED,
        "upstream_url": UPSTREAM_URL, "upstream_sha256": hashlib.sha256(raw).hexdigest(),
        "upstream_license": "CC BY-SA 4.0", "upstream_version": document["version"],
        "selection": "SHA256(seed:question_id), topic round-robin, distinct paragraphs across splits, contexts 150-2400 characters. Select 30 answerable and 30 unanswerable; first 6 of each form development and remaining 24 of each evaluation.",
        "distractors": "Two full 150-650 character paragraphs from different topics, outside selected question paragraphs; exclude occurrences of known reference answer strings. Source order shuffled by per-case hash. Added passages change the official task; alternative answerability is not independently relabeled.",
        "scope": "SQuAD-derived multi-source public development-set subset, not an official leaderboard evaluation or an unseen-data claim. Authored extraction cases are synthetic and separately reported.",
        "extractor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "authored_source_sha256": hashlib.sha256(args.extraction.read_bytes()).hexdigest(),
    }
    hashes = {}
    for split in ("development", "evaluation"):
        target = args.output / f"{split}.json"
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite frozen suite: {target}")
        suite = {"version": "answer-suite-v1", "split": split, "provenance": metadata,
                 "cases": qa[split] + authored[split]}
        target.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + "\n")
        hashes[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {**metadata, "files": hashes,
                "counts": {s: {"qa": len(qa[s]), "extraction": len(authored[s])} for s in qa}}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
