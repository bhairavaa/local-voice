"""Process lifecycle: handshake, supervision, and the HTTP server.

Import from the concrete modules in this package rather than from here. Re-exporting at the
package level makes ``app.runtime.context`` pull in ``app.runtime.server``, which creates an
import cycle through the application factory.
"""

from __future__ import annotations
