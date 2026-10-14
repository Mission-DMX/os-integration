"""Top-level entry point referenced by pysidedeploy.spec's `main_file`.

Nuitka's --standalone/--onefile wants a plain script; the mdmx_explorer
package's own __main__.py exists for `python -m mdmx_explorer` host
testing. Both just call the same main().
"""

import sys

from mdmx_explorer.__main__ import main


if __name__ == "__main__":
    sys.exit(main())
