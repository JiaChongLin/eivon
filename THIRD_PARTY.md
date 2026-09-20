# Third-party notices

Eivon uses dependencies declared in `pyproject.toml` and `console/package.json`. Their licenses are resolved by the package managers and remain in the generated lockfile metadata.

The console references the open-source Manrope and DM Mono fonts through Google Fonts in development and browser builds. Deployments that require offline assets should self-host those fonts according to their upstream licenses or remove the import.

The source export script includes only Git tracked project files; it does not include local credentials, virtual environments, Node dependencies or generated console bundles.
