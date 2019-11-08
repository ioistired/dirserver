#!/usr/bin/env python3

import contextlib
import datetime as dt
import itertools
import os.path
from functools import partial
from pathlib import Path
from werkzeug.routing import PathConverter

import humanize
from flask import Flask, abort, render_template, request

app = Flask(__name__, static_folder=None)
app.jinja_env.add_extension('jinja2.ext.loopcontrols')

# the default is kB which is wrong
humanize.suffixes['decimal'] = ('KB',) + humanize.suffixes['decimal'][1:]

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
		if not p.exists():
			abort(404)
		if not p.is_dir():
			abort(400)
		return p
	def to_url(self, path):
		return super().to_url(str(path))

app.url_map.converters['safe_path'] = SafePathConverter

class DisplayPath:
	def __init__(self, path):
		self.path = path
		self.is_dir = is_dir = path.is_dir()
		self.name = path.name + ('/' if is_dir else '')
		with contextlib.suppress(FileNotFoundError):  # might occur while resolving a symlink
			self.stat = stat = path.stat()
			self.modified = dt.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
			if is_dir:
				self.size = ''
			else:
				self.size = humanize.naturalsize(stat.st_size)

@app.route('/', defaults={'path': config['base_path']})
@app.route('/<safe_path:path>')
def index_dir(path):
	# no hidden
	if any(part.startswith('.') for part in path.parts):
		abort(403)

	paths = path.iterdir()
	if path != config['base_path']:
		# only let people go up a directory if they actually can
		paths = itertools.chain([Path('..')], paths)

	return render_template('list.html', path=request.path, files=map(DisplayPath, paths))

if __name__ == '__main__':
	app.run(use_reloader=True)
