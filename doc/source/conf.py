def setup(app):
    app.add_css_file('css/custom.css')


extensions = [
  'sphinx.ext.autosectionlabel', 'sphinxcontrib.blockdiag',
  'sphinxcontrib.nwdiag', 'sphinx.ext.todo', 'sphinx_fontawesome'
  ]
source_suffix = '.rst'
master_doc = 'index'
project = u''
copyright = u'2022, OSISM GmbH'
author = u'OSISM GmbH'
version = u''
release = u''
language = 'en'
exclude_patterns = []
pygments_style = 'sphinx'
todo_include_todos = True
html_theme = 'sphinx_rtd_theme'
html_show_sphinx = False
html_show_sourcelink = False
html_show_copyright = True
htmlhelp_basename = 'documentation-image-manager'
html_theme_options = {
    'display_version': False,
    # 'canonical_url': 'https://docs.osism.de/',
    'style_external_links': True,
    'logo_only': True,
    'prev_next_buttons_location': None
}
html_context = {
    'display_github': True,
    'github_user': 'osism',
    'github_repo': 'openstack-image-manager',
    'github_version': 'main',
    'conf_py_path': '/source/'
}
html_logo = 'images/logo.png'
html_static_path = [
    '_static'
]
latex_elements = {}
