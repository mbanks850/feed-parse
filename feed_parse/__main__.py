"""Enable ``python -m feed_parse`` as an alias for the ``feed-parse`` CLI."""

from .cli import main

raise SystemExit(main())
