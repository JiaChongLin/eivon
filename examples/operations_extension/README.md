# Operations extension

A second synthetic domain proves that the framework does not require agriculture concepts. Install this module in the deployment environment, set `EIVON_EXTENSIONS=examples.operations_extension`, and create a Tool resource with `adapter: python`, `entrypoint: lookup_status`.

Extension modules are trusted code. Deploy them in a separate image or isolated worker when package authors are not trusted.
