"""Enable ``python -m feedpak`` as an alias for the ``feedpak`` CLI."""

from .cli import main

raise SystemExit(main())
