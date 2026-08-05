"""Entry point for ``python -m learn_upload``.

Launches the PyQt6 GUI wizard by default.  Pass ``--legacy`` to use
the original pywebview GUI instead.
"""

import sys


def main():
    if "--legacy" in sys.argv:
        from learn_upload.gui import main as gui_main
    else:
        from learn_upload.gui_qt import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
