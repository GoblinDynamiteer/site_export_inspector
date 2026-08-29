from __future__ import annotations

import argparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="export-inspector",
        description="Launch the Export Inspector desktop GUI.",
    )
    return parser.parse_args()


def main() -> None:
    parse_args()

    from export_inspector.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
