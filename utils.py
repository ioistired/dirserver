suffixes = ('KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB')

def natural_size(value, format='%.1f'):
	base = 1000
	bytes = float(value)

	if bytes < base: return '%d B' % bytes

	for i, s in enumerate(suffixes, 2):
		unit = base ** i
		if bytes < unit:
			return (format + ' %s') % ((base * bytes / unit), s)
	return (format + ' %s') % ((base * bytes / unit), s)
