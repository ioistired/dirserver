# dirserver

Simple directory indexing web server suited to my needs.

- Lists out all files for the given request path, which is relative to `config['base_path']`.
- Intentionally does not serve static files. This should be handled by your webserver.
- Tries not to list directories outside of the web root.
- Produces a tar archive of any directory (except /, due to routing issues)
  - Symlinks are added as symlinks, not dereferenced.

## License

AGPLv3. See LICENSE.md for details.
