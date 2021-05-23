#!/usr/bin/env python3

# SPDX-License-Identifier: BlueOak-1.0.0

import datetime as dt
import mimetypes
import subprocess
import os
import tempfile
import urllib.parse
import mimetypes
from functools import partial
from pathlib import Path, PurePosixPath

import pygments
import pygments.lexers
import pygments.formatters
import pygments.token
import pygments.util
from pygments.styles.default import DefaultStyle
import werkzeug.exceptions
from flask import Flask, Response, abort, render_template, request, redirect, url_for, make_response
from werkzeug.routing import PathConverter

import utils
import tarfile_stream

ENABLED = frozenset({'1', 'on', 'true'})

plus_as_space = os.environ.get('DIRSERVER_PLUS_AS_SPACE', '0').lower() in ENABLED
if plus_as_space:
	try:
		import gunicorn.util
	except ImportError:
		plus_as_space = False
		print('Warning: DIRSERVER_PLUS_AS_SPACE is enabled but gunicorn was not found. This feature requires gunicorn.')
	else:
		def unquote_to_wsgi_str(string):
			string = string.replace('+', ' ')
			return urllib.parse.unquote_to_bytes(string).decode('latin-1')
		gunicorn.util.unquote_to_wsgi_str = unquote_to_wsgi_str
		del unquote_to_wsgi_str

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = True
app.jinja_env.add_extension('jinja2.ext.loopcontrols')
app.errorhandler(FileNotFoundError)(lambda e: app.handle_http_exception(werkzeug.exceptions.NotFound()))
app.errorhandler(PermissionError)(lambda e: app.handle_http_exception(werkzeug.exceptions.Forbidden()))

if plus_as_space:
	app.jinja_env.filters['urlencode'] = partial(urllib.parse.quote_plus, safe='/')

@app.after_request
def set_server_header(resp):
	# don't leak flask, werkzeug, and python versions
	resp.headers['Server'] = 'Flask'
	return resp

base_path = Path(os.environ['DIRSERVER_BASE_PATH']).resolve()
exclude_hidden = os.environ.get('DIRSERVER_EXCLUDE_HIDDEN', '1').lower() in ENABLED

def ensure_beneath(base_path, path):
	try:
		resolved = (base_path / path).resolve()
	except RuntimeError:  # symlink recursion
		abort(400)

	if base_path not in resolved.parents:
		abort(403)

	return resolved

ensure_in_base_path = partial(ensure_beneath, base_path)

class SafePathConverter(PathConverter):
	def to_python(self, value):
		p = ensure_in_base_path(Path(value))
		if not p.exists():
			abort(404)
		if exclude_hidden and any(part.startswith('.') for part in p.parts):
			abort(403)
		return p

	def to_url(self, path):
		return super().to_url(str(path))

app.url_map.converters['safe_path'] = SafePathConverter

OPUSENC_FLAGS = ['--padding', '0', '--bitrate', '160']

class DisplayPath:
	def __init__(self, path):
		self.path = path
		self.is_file = path.is_file()
		self.is_dir = is_dir = path.is_dir()
		self.is_symlink = path.is_symlink()
		self.dirname = path.relative_to(base_path).parent
		self.name = path.name + ('/' if is_dir else '')
		self.stat = stat = path.lstat()
		self.modified = dt.datetime.fromtimestamp(stat.st_mtime)
		self.size = stat.st_size
		self.natural_size = utils.natural_size(stat.st_size)
		self.highlightable = False
		self.opus_encodable = False
		if self.is_file:
			try:
				pygments.lexers.get_lexer_for_mimetype(mimetypes.guess_type(path.name)[0])
			except pygments.util.ClassNotFound:
				pass
			else:
				self.highlightable = True

			self.opus_encodable = bool(utils.path_is_opusenc_encodable(path))

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
	p = PurePosixPath('/')
	for i, part in enumerate(path.parts[1:]):
		p /= part
		yield Breadcrumb(link=str(p) + '/', text=part)

@app.route('/', defaults={'path': base_path})
@app.route('/<safe_path:path>')
def index_dir(path):
	if not path.is_dir():
		resp = make_response('')
		internal_path = urllib.parse.urljoin('/._protected/', urllib.parse.quote(str(path.relative_to(base_path))))
		resp.headers['X-Accel-Redirect'] = urllib.parse.urljoin('/._protected/', internal_path)
		resp.headers['Content-Type'] = utils.content_type(str(path))
		resp.headers['Content-Disposition'] = utils.content_disposition('inline', path.name)
		return resp
	elif not request.path.endswith('/'):
		return redirect(request.path + '/')

	num_files = num_dirs = 0
	paths = []
	for p in path.iterdir():
		if p.name.startswith('.') and exclude_hidden:
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

	if path != base_path:
		# only let people go up a directory if they actually can
		paths.insert(0, DisplayPath(path / '..'))
		# we can't use with_suffix here because the path doesn't have one,
		# so paths with "." in them would get cut off
		tar_link = urllib.parse.urljoin(request.path, '._tar/' + PurePosixPath(request.path).name + '.tar')
		tar_opus_link = urllib.parse.urljoin(
			request.path,
			'._tar/' + PurePosixPath(request.path).name + '.opus.tar',
		)
	else:
		tar_link = '/._tar/root.tar'
		tar_opus_link = '/._tar/root.opus.tar'

	return render_template(
		'list.html',
		path=request.path,
		items=paths,
		num_files=num_files,
		num_dirs=num_dirs,
		sort=sort_key,
		order=order,
		breadcrumbs=breadcrumbs(PurePosixPath(request.path)),
		tar_link=tar_link,
		tar_opus_link=tar_opus_link,
		is_root=path==base_path,
	)

if exclude_hidden:
	TAR_FILTER = lambda tarinfo: None if any(part.startswith('.') for part in Path(tarinfo.name).resolve().parts) else tarinfo
else:
	TAR_FILTER = None

@app.route('/._tar/<path:dir_name>.tar', defaults={'path': base_path})
@app.route('/<safe_path:path>/._tar/<path:dir_name>.tar')
@app.route('/<safe_path:path>/._tar/<path:dir_name>.opus.tar')
def tar(path, dir_name):
	is_opus = request.path.endswith('.opus.tar')
	def gen():
		tar = tarfile_stream.open(mode='w|')
		yield from tar.header()
		if is_opus:
			yield from opus_adder(tar, path, arcname=Path(dir_name))
		else:
			yield from tar.add(path, arcname='' if path == base_path else dir_name, filter=TAR_FILTER)
		yield from tar.footer()

	resp = Response(gen(), mimetype='application/x-tar')
	resp.headers['Content-Disposition'] = utils.content_disposition('attachment', PurePosixPath(request.path).name)
	return resp

def opus_adder(tar, path, arcname=None):
	if arcname is None:
		if path.is_dir():
			arcname = Path(path.name)
		else:
			arcname = Path(path.with_suffix('.opus').name)

	if path.is_file():
		yield from tar.add(path, filter=TAR_FILTER)
		return

	for f in sorted(path.iterdir()):
		if f.is_dir():
			yield from opus_adder(tar, f, arcname / f.name)
			continue

		if not utils.path_is_opusenc_encodable(f):
			yield from tar.add(f, arcname / f.name, filter=TAR_FILTER)
			continue

		with tempfile.NamedTemporaryFile() as tmp:
			tmp = tmp.name
			proc = subprocess.Popen(
				['opusenc', *OPUSENC_FLAGS, str(f), tmp],
				stdin=subprocess.DEVNULL,
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
				bufsize=0,
			)
			proc.wait()
			yield from tar.add(tmp, (arcname / f.name).with_suffix('.opus'), filter=TAR_FILTER)

@app.route('/._opus/<filename>', defaults={'path': base_path})
@app.route('/<safe_path:path>/._opus/<filename>')
def opus(path, filename):
	path /= filename
	if not utils.path_is_opusenc_encodable(path):
		# just serve it as is
		return index_dir(path)
	encoder_proc = subprocess.Popen(
		['opusenc', *OPUSENC_FLAGS, str(path), '-'],
		stdin=subprocess.DEVNULL,
		stdout=subprocess.PIPE,
		stderr=subprocess.DEVNULL,
		bufsize=0,
	)
	resp = Response(encoder_proc.stdout, mimetype='audio/ogg')
	resp.headers['Content-Disposition'] = utils.content_disposition('inline', path.with_suffix('.opus').name)
	return resp

class PygmentsStyle(DefaultStyle):
	styles = {
		**DefaultStyle.styles,
		pygments.token.Name.Builtin: "",
		pygments.token.Name.Exception: "",
		pygments.token.Operator: DefaultStyle.styles[pygments.token.Keyword],
		pygments.token.Comment.Special: "bg:ansibrightyellow",
	}
	del styles[pygments.token.Operator.Word]

@app.route('/._hl/<filename>', defaults={'path': base_path})
@app.route('/<safe_path:path>/._hl/<filename>')
def highlight(path, filename):
	path /= filename
	if not path.is_file():
		abort(404)

	size = path.stat().st_size
	if size > 10 * 1000 ** 2:
		return redirect(url_for('.index_dir', path=path))

	try:
		code = path.read_text()
	except ValueError:
		return redirect(url_for('.index_dir', path=path))

	try:
		lexer = pygments.lexers.get_lexer_by_name(request.args['lang'])
	except (KeyError, ValueError):
		try:
			lexer = pygments.lexers.get_lexer_for_filename(filename)
		except pygments.util.ClassNotFound:
			lexer = pygments.lexers.get_lexer_by_name('text')

	# highlight "TODO" "XXX" etc
	lexer.add_filter('codetagify')

	formatted = pygments.highlight(code, lexer, pygments.formatters.HtmlFormatter(linenos=True, style=PygmentsStyle))
	relpath = PurePosixPath('/') / path.relative_to(base_path)
	breadcrumbs_ = list(breadcrumbs(relpath))
	breadcrumbs_[-1].link = ''  # current page, as opposed to "raw" link

	return render_template(
		'hl.html',
		code=formatted,
		filename=filename,
		breadcrumbs=breadcrumbs_,
		raw_link=urllib.parse.urljoin('/', str(relpath), filename),
	)

if __name__ == '__main__':
	app.run(host='0.0.0.0', use_reloader=True, debug=True)
