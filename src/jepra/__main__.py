"""`python -m jepra` で起動できるようにする。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
