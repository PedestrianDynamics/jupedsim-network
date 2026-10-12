# SPDX-License-Identifier: LGPL-3.0-or-later
"""Terminal UI of jupedsim-network (``jupedsim-network tui``, #47).

Needs the ``tui`` extra (Textual). :mod:`.model` (the document, paths,
help text, result text) and :mod:`.engine` (the one thread that calls the
package) import no Textual; :mod:`.app` holds the screens.
"""
