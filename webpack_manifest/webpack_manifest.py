"""
webpack_manifest.py - https://github.com/markfinger/python-webpack-manifest

The MIT License (MIT)

Copyright (c) 2015 Mark Finger

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


Description
-----------

Manifest loader that allows you to include references to files built by webpack.

Handles manifests generated by the [webpack-yam-plugin](https://github.com/markfinger/webpack-yam-plugin).


Usage
-----

```
import webpack_manifest

manifest = webpack_manifest.load(
    # An absolute path to a manifest file
    path='/abs/path/to/manifest.json',

    # The root url that your static assets are served from
    static_url='/static/',

    # optional args...
    # ----------------

    # Ensures that the manifest is flushed every time you call `load(...)`
    # If webpack is currently building, it will also delay until it's ready.
    # You'll want to set this to True in your development environment
    debug=False,

    # Max timeout (in seconds) that the loader will wait while webpack is building.
    # This setting is only used when the `debug` argument is True
    timeout=60,

    # If a manifest read fails during deserialization, a second attempt will be
    # made after a small delay. By default, if `read_retry` is `None` and `debug`
    # is `True`, it well be set to `1`
    read_retry=None,
)

# `load` returns a manifest object with properties that match the names of
# the entries in your webpack config. The properties matching your entries
# have `js` and `css` properties that are pre-rendered strings that point
# to all your JS and CSS assets. Additionally, tuples of relative urls are
# available under `rel_js` and `rel_css` properties.

# A string containing pre-rendered script elements for the "main" entry
manifest.main.js  # '<script src="/static/path/to/file.js"><script><script ... >'

# A string containing pre-rendered link elements for the "main" entry
manifest.main.css  # '<link rel="stylesheet" href="/static/path/to/file.css"><link ... >'

# A string containing pre-rendered link elements for the "vendor" entry
manifest.vendor.css  # '<link rel="stylesheet" href="/static/path/to/file.css"><link ... >'

# A tuple containing relative urls (without the static url) to the "vender" entry
manifest.vendor.rel_css  # ('path/to/file.css', 'path/to/another.css', ...)

# Note: If you don't name your entry, webpack will automatically name it "main".
```
"""

import os
import json
import time
from datetime import datetime, timedelta

__version__ = '1.0.0'

MANIFEST_CACHE = {}

BUILDING_STATUS = 'building'
BUILT_STATUS = 'built'
ERRORS_STATUS = 'errors'


def load(path, static_url, debug=False, timeout=60, read_retry=None):
    # Enable failed reads to be retried after a delay of 1 second
    if debug and read_retry is None:
        read_retry = 1

    if debug or path not in MANIFEST_CACHE:
        manifest = build(path, static_url, debug, timeout, read_retry)

        if not debug:
            MANIFEST_CACHE[path] = manifest

        return manifest

    return MANIFEST_CACHE[path]


def build(path, static_url, debug, timeout, read_retry):
    data = read(path, read_retry)
    status = data.get('status', None)

    if debug:
        # Lock up the process and wait for webpack to finish building
        max_timeout = datetime.utcnow() + timedelta(seconds=timeout)
        while status == BUILDING_STATUS:
            time.sleep(0.1)
            if datetime.utcnow() > max_timeout:
                raise WebpackManifestBuildingStatusTimeout(
                    'Timed out reading the webpack manifest at "{}"'.format(path)
                )
            data = read(path, read_retry)
            status = data.get('status', None)

    if status == ERRORS_STATUS:
        raise WebpackError(
            'Webpack errors: \n\n{}'.format(
                '\n\n'.join(data['errors'])
            )
        )

    if status != BUILT_STATUS:
        raise WebpackManifestStatusError('Unknown webpack manifest status: "{}"'.format(status))

    return WebpackManifest(data['files'], static_url)


class WebpackManifest(object):
    def __init__(self, files, static_url):
        for entry in files:
            manifest_entry = WebpackManifestEntry(files[entry], static_url)
            setattr(self, entry, manifest_entry)


class WebpackManifestEntry(object):
    def __init__(self, rel_paths, static_url):
        self.js = ''
        self.rel_js = ()
        self.css = ''
        self.rel_css = ()

        # Frameworks tend to be inconsistent about what they
        # allow with regards to static urls
        if not static_url.endswith('/'):
            static_url += '/'

        # Build strings of elements that can be dumped into a template
        for rel_path in rel_paths:
            name, ext = os.path.splitext(rel_path)
            rel_url = '/'.join(rel_path.split(os.path.sep))
            if ext == '.js':
                self.js += '<script src="{}{}"></script>'.format(static_url, rel_url)
                self.rel_js += (rel_url,)
            elif ext == '.css':
                self.css += '<link rel="stylesheet" href="{}{}">'.format(static_url, rel_url)
                self.rel_css += (rel_url,)

        self._contents = rel_paths
        self._static_url = static_url


def read(path, read_retry):
    if not os.path.isfile(path):
        raise WebpackManifestFileError('Path "{}" is not a file or does not exist'.format(path))

    if not os.path.isabs(path):
        raise WebpackManifestFileError('Path "{}" is not an absolute path to a file'.format(path))

    with open(path, 'r') as manifest_file:
        content = manifest_file.read().encode('utf-8')

    # In certain conditions, the file's contents evaluate to an empty string, so
    # we provide a hook to perform a single retry after a delay.
    # While it's a difficult bug to pin down it can happen most commonly during
    # periods of high cpu-load, so the suspicion is that it's down to race conditions
    # that are a combination of delays in the OS writing buffers and the fact that we
    # are handling two competing processes
    try:
        return json.loads(content)
    except ValueError:
        if not read_retry:
            raise

        time.sleep(read_retry)
        return read(path, 0)


class WebpackManifestFileError(Exception):
    pass


class WebpackError(Exception):
    pass


class WebpackManifestStatusError(Exception):
    pass


class WebpackManifestBuildingStatusTimeout(Exception):
    pass
