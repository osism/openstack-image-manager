def setup(app):
    app.add_css_file("css/custom.css")


extensions = [
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.todo",
    "sphinx_fontawesome",
]
source_suffix = ".rst"
master_doc = "index"
project = ""
copyright = "2022, OSISM GmbH"
author = "OSISM GmbH"
version = ""
release = ""
language = "en"
exclude_patterns = []
pygments_style = "sphinx"
todo_include_todos = True
html_theme = "sphinx_material"
html_show_sphinx = False
html_show_sourcelink = False
html_show_copyright = True
htmlhelp_basename = "openstack-image-manager"
html_theme_options = {
    "nav_title": "OSISM OpenStack Image Manager",
    "color_primary": "blue",
    "color_accent": "light-blue",
    "globaltoc_depth": 3,
    "globaltoc_collapse": True,
}
html_context = {}
html_title = "OSISM OpenStack Image Manager"
html_logo = "images/logo.png"
html_sidebars = {
    "**": ["logo-text.html", "globaltoc.html", "localtoc.html", "searchbox.html"]
}
latex_elements = {}
