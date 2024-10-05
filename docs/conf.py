exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", ".venv", "venv"]
html_css_files = ["literals.css"]
extensions = ["sphinx_rtd_theme", "sphinx-prompt"]
templates_path = ["_templates"]

html_context = {
    "display_github": True,
    "github_user": "LeDeathAmongst",
    "github_repo": "Dashboard",
    "github_version": "main",
}

master_doc = "index"
html_theme = "furo"
source_suffix = ".rst"
master_doc = "index"
exclude_patterns = []
add_function_parentheses = True

project = "Starfire Dashboard"
copyright = "2024 | Star"
