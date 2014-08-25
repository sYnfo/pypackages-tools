#!/usr/bin/python3
# TODO: we should fail/warn when there is a python libdir without installed runtime
from __future__ import print_function

import argparse
try:
    import configparser
except ImportError:
    import ConfigParser as configparser
import codecs
import copy
import glob
import logging
import os
import subprocess
import sys


PYTHON_LIBDIRS = [os.path.join('usr', 'lib', 'python[0-9].[0-9]'),
    os.path.join('usr', 'lib64', 'python[0-9].[0-9]')]
logging.basicConfig(format=os.path.basename(__file__) + ': %(message)s', level=logging.INFO)


class ByteCompileConfig(object):
    _flags_variations = ['', '-O']

    def __init__(self, fname, **kwargs):
        self.fname = fname
        self._rootdir = kwargs.get('rootdir', os.path.sep)
        self._default_for_rootdir = kwargs.get('default_for_rootdir', '0')
        self._flags = kwargs.get('flags', '')
        self._python = kwargs.get('python',
            os.path.join(os.path.sep, '{rootdir}', 'usr', 'bin', '{fname}'))
        self._compile_dirs = kwargs.get('compile_dirs',
            os.path.join(os.path.sep, '{rootdir}', 'usr', 'lib', '{fname}') + ':' +
            os.path.join(os.path.sep, '{rootdir}', 'usr', 'lib64', '{fname}'))
        self._inline_script = kwargs.get('inline_script', 'import compileall, sys;' + \
            'sys.exit(not compileall.compile_dir("{python_libdir}", {depth}, "{real_libdir}",' + \
            'force=1, quiet=1))')
        self._run = kwargs.get('run', "{python} {flags} -c '{inline_script}'")
        # TODO: check format of provided attributes

        # not create non-underscored versions of some attributes
        self.formatted_dict = {'fname': self.fname}
        self.formatted_dict['rootdir'] = self._rootdir.format(**self.formatted_dict)
        self.formatted_dict['default_for_rootdir'] = (self._default_for_rootdir == '1')
        self.formatted_dict['flags'] = self._flags  # no formatting for flags for now
        self.formatted_dict['python'] = self._python.format(**self.formatted_dict)
        self.formatted_dict['compile_dirs'] = \
            self._compile_dirs.format(**self.formatted_dict).split(':')

    def get_depth(self, directory):
        # TODO
        return 1000

    def get_run_strings(self, rpm_buildroot):
        flags_variations = []
        for f in self._flags_variations:
            flags_variations.append(self.formatted_dict['flags'] + ' ' + f)

        run_strings = []
        # first, obtain run strings for libdirs
        for l in self.formatted_dict['compile_dirs']:
            # can't use os.path.join, since l is absolute
            python_libdir = rpm_buildroot + l
            if not os.path.exists(python_libdir):
                continue
            real_libdir = l
            # construct the whole inline script
            form_dict = dict(python_libdir=python_libdir, depth=self.get_depth(l),
                real_libdir=real_libdir, **self.formatted_dict)
            inline_script = self._inline_script.format(**form_dict)
            form_dict['inline_script'] = inline_script

            # construct the whole commands
            for f in flags_variations:
                form_dict['flags'] = f
                run_strings.append(self._run.format(**form_dict))

        # then, if self.formatted_dict['default_for_rootdir'], obtain run string
        #  for compiling the whole self.formatted_dict['rootdir']
        # TODO: this has to know about other roots, so that it can ignore them

        return run_strings

    @classmethod
    def from_file(cls, fullpath):
        parser = configparser.SafeConfigParser()
        # open a file first, so that we're sure it's opened with utf-8
        with codecs.open(fullpath, 'r', 'utf-8') as fp:
            parser.readfp(fp)

        # first handle values that are not in _conf_file_autovalues
        fname = os.path.splitext(os.path.split(fullpath)[1])[0]
        items = []
        if parser.has_section('bytecompile'):
            items = parser.items('bytecompile')
        return cls(fname, **dict(items))


def bytecompile(rpm_buildroot, default_python, errors_terminate, config_dir, dry_run):
    # normalize rpm_buildroot, removing duplicate slashes
    rpm_buildroot = os.path.abspath(rpm_buildroot)
    if rpm_buildroot == '/':
        return 0
    configs = _load_configs(config_dir)

    if compile_roots_errors(configs):
        return 10
    if unassoc_libdirs_errors(configs, rpm_buildroot):
        return 11

    to_run = {}
    for fname, config in configs.items():
        to_run[fname] = config.get_run_strings(rpm_buildroot=rpm_buildroot)

    if dry_run:
        for fname, run_strings in to_run.items():
            logging.info('Running from {fname}:'.format(fname))
            logging.info(run_strings)

    return 0


def unassoc_libdirs_errors(configs, rpm_buildroot):
    buildroot_libdirs = []
    for pld in PYTHON_LIBDIRS:
        ld_fullpath_normalized = os.path.abspath(os.path.join(rpm_buildroot, pld))
        buildroot_libdirs.extend(glob.glob(ld_fullpath_normalized))

    config_libdirs = []
    for cf in configs.items():
        # can't use os.path.join, since config.formatted_dict['compile_dirs']
        #  contains absolute paths
        libdirs = [os.path.abspath(rpm_buildroot + l) for l in cf.formatted_dict['compile_dirs']]
        config_libdirs.extend(libdirs)

    not_matched = set(buildroot_libdirs) - set(config_libdirs)

    if not_matched:
        logging.error('Error: there are Python libdirs not associated with any Python runtime:')
        [logging.error(nm) for nm in not_matched]
        return True

    return False


def compile_roots_errors(configs):
    """Check that there isn't a root with two or more default Pythons."""
    # mapping {config_filename: rootdir}
    compile_roots = {}
    for fname, config in configs.items():
        if config.formatted_dict['default_for_rootdir']:
            # normalize the path by os.path.abspath
            compile_roots[fname] = os.path.abspath(config.formatted_dict['rootdir'])

    # mapping {rootdir: [config_filename, ...]}
    path_to_pythons = {}
    for python, path in compile_roots.items():
        path_to_pythons.setdefault(path, [])
        path_to_pythons[path].append(python)

    errs = {path: pythons for path, pythons in path_to_pythons.items() if len(pythons) > 1}
    if errs:
        logging.error('Config error, following roots are to be compiled by multiple Pythons:')
        logging.error(errs, file=sys.stderr)
        return True

    return False


def _load_configs(location):
    configs = {}
    for cf in glob.glob(os.path.join(location, '*.conf')):
        config = ByteCompileConfig.from_file(cf)
        configs[config.fname] = config
    return configs


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    # TODO: document that default_python is only here for backwards compat
    #  (or remove it altogether)
    parser.add_argument('default_python', default=None)
    parser.add_argument('errors_terminate', default=None)
    parser.add_argument('--dry-run', action='store_true', default=False)
    parser.add_argument('--config-dir', default='/etc/pypackages-tools/')

    args = parser.parse_args()
    rpm_buildroot = os.environ.get('RPM_BUILD_ROOT', '/')
    sys.exit(bytecompile(rpm_buildroot=rpm_buildroot, **vars(args)))
