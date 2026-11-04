#!/usr/bin/env python3
"""Build private complete Code.gs without publishing the private original.

python apps_script/build_complete.py --source /private/Code.gs --output /private/Code.gs
Reads the stable source, adds one guarded hook and appends the public adapter.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

HOOK = """    // Moneyball 8.0 consumes only the public NFL forecast; prior modules stay intact.
    try {
      mb8Run_(folder, week);
    } catch (mb8Error) {
      Logger.log('MONEYBALL 8.0 NO ACTUALIZADO; corte previo conservado: ' + mb8Error.message);
    }
"""


def build(source: str, extension: str) -> str:
    if "const MB8 =" in source:
        raise ValueError("Source already contains Moneyball 8; use stable 7.2.1 source")
    anchor = "    const filled = ourRoster.starters.filter(id => id !== null && String(id) !== '0').length;"
    if source.count(anchor) != 1:
        raise ValueError("Expected exactly one verified update hook anchor")
    result = source.replace(anchor, HOOK + anchor) + "\n\n" + extension
    names = re.findall(r"^function\s+(\w+)\s*\(", result, re.M)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"Duplicate function declarations: {duplicates}")
    old = set(re.findall(r"^function\s+(\w+)\s*\(", source, re.M))
    if not old.issubset(names):
        raise ValueError("An existing function was lost")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    extension = Path(__file__).with_name("moneyball8_extension.js").read_text()
    result = build(args.source.read_text(), extension)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result)
    print(f"COMPLETE_CODE_GS_BUILT {args.output} bytes={args.output.stat().st_size}")
