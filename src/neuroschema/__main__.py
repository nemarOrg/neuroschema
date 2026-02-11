"""Allow running neuroschema as a module: python -m neuroschema."""

import sys

from neuroschema.validate import main

sys.exit(main())
