# SPDX-License-Identifier: LGPL-3.0-or-later
project = "jupedsim-network"
author = "JuPedSim developers"
copyright = "JuPedSim developers"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosectionlabel",
]
autosectionlabel_prefix_document = True
myst_enable_extensions = ["amsmath", "colon_fence", "dollarmath"]
exclude_patterns = ["_scripts"]

html_theme = "sphinx_book_theme"
html_title = "jupedsim-network"
html_theme_options = {
    "repository_url": "https://github.com/PedestrianDynamics/jupedsim-network",
    "use_repository_button": True,
}
