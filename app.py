#!/usr/bin/env python3

import os.path
from functools import partial
from pathlib import Path
from werkzeug.routing import PathConverter

from flask import Flask, abort

app = Flask(__name__, static_folder=None)

with open('config.py') as f:
	config = eval(f.read(), {'Path': Path})

def is_beneath(base_path, path):
	try:
		resolved = (base_path / path).resolve()
	except (RuntimeError, FileNotFoundError):
		return False

	return base_path in resolved.parents and resolved

is_in_base_path = partial(is_beneath, config['base_path'])

class SafePathConverter(PathConverter):
	def to_python(self, value):
		p = is_in_base_path(Path(value))
		if not p:
			abort(400)
		return p
	def to_url(self, path):
		return super().to_url(str(path))

app.url_map.converters['safe_path'] = SafePathConverter

@app.route('/', defaults={'path': '/'})
@app.route('/<safe_path:path>')
def get_dir(path):
	# no hidden
	if any(part.startswith('.') for part in path.parts):
		abort(403)
	return str(path)

if __name__ == '__main__':
	app.run(use_reloader=True)
