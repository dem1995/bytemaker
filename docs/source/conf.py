# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys

sys.path.insert(0, os.path.abspath("../"))
sys.path.insert(0, os.path.abspath("../bytemaker"))
sys.path.insert(0, os.path.abspath("../bytemaker/conversions"))

# sys.path.insert(0, os.path.abspath("../bytemaker/bitvector"))
# sys.path.insert(0, os.path.abspath("../bytemaker/bittypes"))

# sys.path.insert(0, os.path.abspath("../bytemaker/native_types"))


project = "bytemaker"
copyright = "2023, DEMcKnight"
author = "DEMcKnight"
version = "0.9.2"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.coverage",
    "sphinx.ext.doctest",
    "sphinx.ext.autosummary",
    "sphinx.ext.graphviz",
    "sphinx.ext.ifconfig",
    "sphinx.ext.mathjax",
    "sphinx_copybutton",
    "sphinx_design",
    "nbsphinx",
]

autosummary_generate = True  # Generate stub pages for API documentation
autodoc_inherit_docstrings = True  # Prevent docstring inheritance

templates_path = ["_templates"]
exclude_patterns = []
# autodoc_member_order = "bysource"


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# html_css_files = [
#     "custom.css",
# ]
# html_js_files = [
#     'https://kit.fontawesome.com/73afaef361.js',
# ]
html_css_files = [
    "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.1.1/css/all.min.css"
]
html_theme = "piccolo_theme"
# html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_logo = "./_static/bytemaker_logo_with_title.png"
source_encoding = "utf-8-sig"


def setup(app):
    app.add_css_file("custom.css")
    app.add_js_file("custom.js")


html_theme_options = {
    "source_url": "https://github.com/dem1995/bytemaker",
    "github_url": "https://github.com/dem1995/bytemaker",
    # "collapse_navigation": True,
    # "switcher": {
    #     "version_match": version
    # }
    # "navbar_end": ["theme-switcher", "version-switcher"],
    # 'analytics_id': 'G-XXXXXXXXXX',  #  Provided by Google in your dashboard
    # 'analytics_anonymize_ip': False,
    # 'logo_only': False,
    # 'display_version': True,
    # 'prev_next_buttons_location': 'bottom',
    # 'style_external_links': False,
    # 'vcs_pageview_mode': '',
    # 'style_nav_header_background': 'white',
    # Toc options
    # 'collapse_navigation': False,
    # 'sticky_navigation': True,
    # 'navigation_depth': 4,
    # 'includehidden': True,
    # 'titles_only': False
}


# html_theme_options = {
#     "logo": {
#         "image_light": "_static/numpylogo.svg",
#         "image_dark": "_static/numpylogo_dark.svg",
#     },
#     "github_url": "https://github.com/numpy/numpy",
#     "collapse_navigation": True,
#     "external_links": [
#         {"name": "Learn", "url": "https://numpy.org/numpy-tutorials/"},
#         {"name": "NEPs", "url": "https://numpy.org/neps"},
#     ],
#     "header_links_before_dropdown": 6,
#     # Add light/dark mode and documentation version switcher:
#     "navbar_end": [
#         "search-button",
#         "theme-switcher",
#         "version-switcher",
#         "navbar-icon-links"
#     ],
#     "navbar_persistent": [],
#     "switcher": {
#         "version_match": switcher_version,
#         "json_url": "https://numpy.org/doc/_static/versions.json",
#     },
#     "show_version_warning_banner": True,
# }
