#!/usr/bin/env python3
"""Run a no-inference policy control on declared applicable live-evaluation cases."""

import argparse
import json

from agentproof.rules_reference import run_reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        result = run_reference(args.reference, args.output_dir)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Rules reference refused: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
