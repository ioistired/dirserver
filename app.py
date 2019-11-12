#!/usr/bin/env python3

import datetime as dt
import platform
import subprocess
import urllib.parse
from functools import partial
from pathlib import Path, PurePosixPath

import flask
import werkzeug
import werkzeug.exceptions
from flask import Flask, Response, abort, render_template, request
from werkzeug.routing import PathConverter

import utils
import tarfile_stream

class Flask(Flask):
	def process_response(self, response):
		response.headers['Server'] = (
			'dirserver '
			f'Flask/{flask.__version__} '
			f'Werkzeug/{werkzeug.__version__} '
			f'Python/{platform.python_version()}'
		)
		super().process_response(response)
		return response

app = Flask(__name__, static_folder=None)
app.jinja_env.add_extension('jinja2.ext.loopcontrols')
app.errorhandler(FileNotFoundError)(lambda e: app.handle_http_exception(werkzeug.exceptions.NotFound()))
app.errorhandler(PermissionError)(lambda e: app.handle_http_exception(werkzeug.exceptions.Forbidden()))

with open('config.py') as f:
	config = eval(f.read(), {'Path': Path})

config['base_path'] = Path(config['base_path']).resolve()  # just in case it's a str

def ensure_beneath(base_path, path):
	try:
		resolved = (base_path / path).resolve()
	except RuntimeError:  # symlink recursion
		abort(400)

	if base_path not in resolved.parents:
		abort(403)

	return resolved

ensure_in_base_path = partial(ensure_beneath, config['base_path'])

class SafePathConverter(PathConverter):
	def to_python(self, value):
		p = ensure_in_base_path(Path(value))
		if not p.exists():
			abort(404)
		if not p.is_dir():
			abort(400)
		if config.get('exclude_hidden', True) and any(part.startswith('.') for part in p.parts):
			abort(403)
		return p

	def to_url(self, path):
		return super().to_url(str(path))

app.url_map.converters['safe_path'] = SafePathConverter

class DisplayPath:
	def __init__(self, path):
		self.path = path
		self.is_file = path.is_file()
		self.is_dir = is_dir = path.is_dir()
		self.is_symlink = path.is_symlink()
		self.name = path.name + ('/' if is_dir else '')
		self.stat = stat = path.lstat()
		self.modified = dt.datetime.fromtimestamp(stat.st_mtime)
		self.size = stat.st_size
		self.natural_size = utils.natural_size(stat.st_size)

def dir_first(p, key): return (0 if p.is_dir else 1, key)

sort_keys = {
	'namedirfirst': lambda p: dir_first(p, p.name.lower()),
	'name': lambda p: p.name.lower(),
	'time': lambda p: p.modified,
	'size': lambda p: dir_first(p, p.name.lower() if p.is_dir else p.size),
}

class Breadcrumb:
	def __init__(self, link, text):
		self.link = link
		self.text = text

def breadcrumbs(path):
	for i, part in enumerate(path.parts[1:]):
		yield Breadcrumb(link='../' * (len(path.parts) - i - 2), text=part)

@app.route('/', defaults={'path': config['base_path']})
@app.route('/<safe_path:path>/')
def index_dir(path):
	num_files = num_dirs = 0
	paths = []
	for p in path.iterdir():
		if p.name.startswith('.') and config.get('exclude_hidden', True):
			continue
		p = DisplayPath(p)
		if p.is_dir:
			num_dirs += 1
		elif p.is_file:
			num_files += 1
		paths.append(p)

	sort_key = request.args.get('sort', 'namedirfirst')
	order = request.args.get('order', 'asc')
	paths.sort(key=sort_keys.get(sort_key, sort_keys['namedirfirst']), reverse=order == 'desc')

	can_tar = False
	if path != config['base_path']:
		# only let people go up a directory if they actually can
		paths.insert(0, DisplayPath(path / '..'))
		can_tar = True

	return render_template(
		'list.html',
		path=request.path,
		items=paths,
		num_files=num_files,
		num_dirs=num_dirs,
		sort=sort_key,
		order=order,
		breadcrumbs=breadcrumbs(PurePosixPath(request.path)),
		tar_link=can_tar and urllib.parse.urljoin(request.path, '._tar/' + PurePosixPath(request.path).name + '.tar'),
	)

if config.get('exclude_hidden', True):
	TAR_FILTER = lambda tarinfo: None if any(part.startswith('.') for part in Path(tarinfo.name).parts) else tarinfo
else:
	TAR_FILTER = None

@app.route('/<safe_path:path>/._tar/<dir_name>.tar')
def tar(path, dir_name):
	def gen():
		tar = tarfile_stream.open(mode='w|')
		yield from tar.add(path, arcname=path.name, filter=TAR_FILTER)
		yield from tar.footer()

	return Response(gen(), mimetype='application/x-tar')

if __name__ == '__main__':
	app.run(use_reloader=True)
