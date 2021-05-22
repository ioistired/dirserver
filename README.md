# dirserver

Simple directory indexing web server suited to my needs.

- Lists out all files for the given request path, which is relative to `DIRSERVER_BASE_PATH`.
- Intentionally does not serve static files. This should be handled by your webserver.
- Tries not to list directories outside of the web root.
- Produces a tar archive of any directory (except /, due to routing issues)
  - Symlinks are added as symlinks, not dereferenced.

## Configuration

All configuration is done via environment variables. There are three:

- `DIRSERVER_BASE_PATH`: the path to the root of all files to serve. Required.
- `DIRSERVER_EXCLUDE_HIDDEN`: whether to hide files whose name starts with a dot. Optional, defaults to `1`.
- `DIRSERVER_PLUS_AS_SPACE`: whether to use `+` instead of `%20` to represent space characters in URLs. Requires gunicorn. Defaults to `0`.

## License

- My code: BlueOak v1.0.0. See LICENSE.md for details.
- `tarfile_stream.py`: MIT. See that file's header for details.
- `templates/list.html`: Apache-2.0. See that file's header for more details.
