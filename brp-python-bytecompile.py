#!/usr/bin/python3
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


def path_norm_join(path, *more):
    """Normalize a path using os.path.abspath. If more paths are given,
    they are merged, normalized and returned. Unlike os.path.join, this
    also works when any of the paths is/are absolute."""
    result = [path]
    result.extend(more)
    # if there are two slashes in the start, os.path.abspath won't normalize
    #  TODO: find out why this happens
    joined = os.path.abspath(os.path.sep.join(result))
    if joined.startswith(os.path.sep * 2) and not joined.startswith(os.path.sep * 3):
        return joined[1:]
    return joined


PYTHON_LIBDIRS = [path_norm_join(os.path.sep, 'usr', 'lib', 'python[0-9].[0-9]'),
    path_norm_join(os.path.sep, 'usr', 'lib64', 'python[0-9].[0-9]')]
logging.basicConfig(format=os.path.basename(__file__) + ': %(message)s', level=logging.INFO)


class ByteCompileConfig(object):
    _flags_variations = ['', '-O']

    def __init__(self, fname, **kwargs):
        """Initializes ByteCompileConfig object. Configuration options are stored as
        underscored values - rootdir, default_for_rootdir, flags, python, compile_dirs,
        inline script and run.

        A formatted_dict attribute with some formatted values (rootdir, default_for_rootdir,
        flags, python and compile_dirs) is initialized. inline_script and run aren't
        in formatted_dict, since they are supposed to be used more times to construct
        different invocation strings."""
        self.fname = fname
        self._rootdir = kwargs.get('rootdir', os.path.sep)
        self._default_for_rootdir = kwargs.get('default_for_rootdir', '0')
        self._flags = kwargs.get('flags', '')
        self._python = kwargs.get('python',
            path_norm_join(os.path.sep, '{rootdir}', 'usr', 'bin', '{fname}'))
        self._compile_dirs = kwargs.get('compile_dirs',
            path_norm_join(os.path.sep, '{rootdir}', 'usr', 'lib', '{fname}') + ':' +
            path_norm_join(os.path.sep, '{rootdir}', 'usr', 'lib64', '{fname}'))
        self._inline_script = kwargs.get('inline_script', 'import compileall, sys, re; ' + \
            'sys.exit(not compileall.compile_dir("{compile_dir}", {depth}, "{real_dir}", ' + \
            'force=1, quiet=1, rx={rx}))')
        self._run = kwargs.get('run', "{python} {flags} -c '{inline_script}'")
        # TODO: check format of provided attributes

        # not create non-underscored versions of some attributes
        self.formatted_dict = {'fname': self.fname}
        self.formatted_dict['rootdir'] = path_norm_join(self._rootdir.format(**self.formatted_dict))
        self.formatted_dict['default_for_rootdir'] = (self._default_for_rootdir == '1')
        self.formatted_dict['flags'] = self._flags  # no formatting for flags for now
        self.formatted_dict['python'] = \
            path_norm_join(self._python.format(**self.formatted_dict))
        self.formatted_dict['compile_dirs'] = \
            [path_norm_join(p) for p in self._compile_dirs.format(**self.formatted_dict).split(':')]

    def get_depth(self, directory):
        """Get depth of given directory."""
        dir_slashes = directory.count(os.path.sep)
        return max((path[0].count(os.path.sep) for path in os.walk(directory))) - dir_slashes

    def get_compile_invocations(self, rpm_buildroot, exclude_dirs=[]):
        """Returns a list of proper bytecompilation invocations that are to be called
        based on this config.

        Args:
            rpm_buildroot: rpm buildroot path
            exclude_dirs: dirs to be excluded from bytecompilation by this Python
        Returns:
            list of strings that can be invoked by subprocess.Popen
        """
        flags_variations = []
        for f in self._flags_variations:
            flags_variations.append(' '.join([self.formatted_dict['flags'], f]).strip())

        invocations = self._get_libdir_compile_invocations(rpm_buildroot, flags_variations)
        invocations.extend(self._get_rootdir_compile_invocations(rpm_buildroot,
            flags_variations, exclude_dirs))

        return invocations

    def _get_libdir_compile_invocations(self, rpm_buildroot, flags_variations):
        """Returns a list of proper bytecompilation invocations that are to called
        based on compile_dirs of this config.

        Args:
            rpm_buildroot: rpm buildroot path
            flags_variations: list of strings, each string containing one variation
                of flags that are to be used for bytecompilation for every directory

        Returns:
            list of strings that can be invoked by subprocess.Popen
        """
        invocations = []
        # first, obtain run strings for libdirs
        for l in self.formatted_dict['compile_dirs']:
            compile_dir = path_norm_join(rpm_buildroot, l)
            if not os.path.exists(compile_dir):
                continue
            real_dir = l
            # construct the whole inline script
            form_dict = dict(compile_dir=compile_dir,
                depth=self.get_depth(compile_dir),
                real_dir=real_dir, rx=None, **self.formatted_dict)
            form_dict['inline_script'] = self._inline_script.format(**form_dict)

            # construct the whole commands
            for f in flags_variations:
                form_dict['flags'] = f
                invocations.append(self._run.format(**form_dict))

        return invocations

    def _get_rootdir_compile_invocations(self, rpm_buildroot, flags_variations, exclude_dirs):
        """Returns a list of proper bytecompilation invocations that are to called
        for compilation of rootdir of this config (empty if this config doesn't
        say that rootdir should be compiled).

        Args:
            rpm_buildroot: rpm buildroot path
            flags_variations: list of strings, each string containing one variation
                of flags that are to be used for bytecompilation for every directory
            exclude_dirs: dirs to be excluded from root bytecompilation

        Returns:
            list of strings that can be invoked by subprocess.Popen, possibly empty
            if this config doesn't say that rootdir should be compiled
        """
        invocations = []
        if self.formatted_dict['default_for_rootdir']:
            full_rootdir = path_norm_join(rpm_buildroot, self.formatted_dict['rootdir'])
            # we can really exclude only these dirs that are not superdirs of rootdir
            really_exclude = [d for d in exclude_dirs if not full_rootdir.startswith(d)]

            rx = "re.compile(r'{0}')".format('|'.join(really_exclude))
            form_dict = dict(compile_dir=full_rootdir,
                depth=self.get_depth(full_rootdir),
                real_dir=self.formatted_dict['rootdir'], rx=rx, **self.formatted_dict)
            form_dict['inline_script'] = self._inline_script.format(**form_dict)

            for f in flags_variations:
                form_dict['flags'] = f
                invocations.append(self._run.format(**form_dict))

        return invocations

    @classmethod
    def from_file(cls, fullpath):
        """A class method that instantiates and returns a config from a given file path."""
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
    """Does the bytecompilation as specified in all configs.

    Args:
        rpm_buildroot: rpm buildroot
        default_python: ignored for now (and probably forever)
        errors_terminate: should errors terminate bytecompilation imediatelly?
        config_dir: a directory where to look for config files
        dry_run: if True, subprocesses won't actually be invoked, but rather
            only logged

    Returns:
        0 if everything goes well
        10 if some configs want to compile the same root
        11 if there are Python libdirs unassociated with any config
        TODO
    """
    # normalize rpm_buildroot, removing duplicate slashes
    rpm_buildroot = path_norm_join(rpm_buildroot)
    if rpm_buildroot == '/':
        return 0
    configs = load_configs(config_dir)

    if compile_roots_errors(configs):
        return 10
    if unassoc_libdirs_errors(configs, rpm_buildroot):
        return 11

    to_run = {}
    for fname, config in configs.items():
        # get list of dirs to exclude when compiling by this config
        exclude_dirs = get_exclude_dirs(configs, rpm_buildroot, fname)
        to_run[fname] = \
            config.get_compile_invocations(rpm_buildroot=rpm_buildroot, exclude_dirs=exclude_dirs)

    if dry_run:
        for fname, run_strings in to_run.items():
            logging.info('Running from config "{0}":'.format(fname))
            [logging.info(rs) for rs in sorted(run_strings)]
    else:
        pass  # TODO: actually do stuff

    return 0


def unassoc_libdirs_errors(configs, rpm_buildroot):
    """Find out if there are Python libdirs unassociated with any config.
    Logs the problematic libdirs, if any.

    Args:
        configs: mapping of config names to ByteCompileConfig objects
        rpm_buildroot: rpm buildroot to search

    Returns:
        True if problems were found, False otherwise
    """
    buildroot_libdirs = []
    for pld in PYTHON_LIBDIRS:
        ld_fullpath_normalized = path_norm_join(rpm_buildroot, pld)
        buildroot_libdirs.extend(glob.glob(ld_fullpath_normalized))

    config_libdirs = []
    for cf in configs.values():
        libdirs = [path_norm_join(rpm_buildroot, l) for l in cf.formatted_dict['compile_dirs']]
        config_libdirs.extend(libdirs)

    not_matched = set(buildroot_libdirs) - set(config_libdirs)

    if not_matched:
        logging.error('Error: there are Python libdirs not associated with any Python runtime:')
        [logging.error(nm) for nm in sorted(not_matched)]
        return True

    return False


def compile_roots_errors(configs):
    """Check that there isn't a rootdir with two or more default Pythons.
    Logs the problematic rootdirs and respective configs, if any.

    Args:
        configs: mapping of config names to ByteCompileConfig objects

    Returns:
        True if problems were found, False otherwise
    """
    # mapping {config_filename: rootdir}
    compile_roots = {}
    for fname, config in configs.items():
        if config.formatted_dict['default_for_rootdir']:
            compile_roots[fname] = path_norm_join(config.formatted_dict['rootdir'])

    # mapping {rootdir: [config_filename, ...]}
    path_to_pythons = {}
    for python, path in compile_roots.items():
        path_to_pythons.setdefault(path, [])
        path_to_pythons[path].append(python)

    errs = {path: pythons for path, pythons in path_to_pythons.items() if len(pythons) > 1}
    if errs:
        logging.error('Error, following roots are to be compiled by multiple Pythons:')
        for root, confs in sorted(errs.items()):
            err_msg = '"{root}": {confs}'.format(root=root, confs=', '.join(sorted(confs)))
            logging.error(err_msg)
        return True

    return False


def get_exclude_dirs(configs, rpm_buildroot, current):
    """Get list of directories to be excluded by rootdir compilation of specified config.

    Args:
        configs: mapping of config names to ByteCompileConfig objects
        rpm_buildroot: rpm buildroot
        current: name of config to get exclude strings for (it's own directories are
            not included in the output)

    Returns:
        list of directories to exclude by given config
    """
    # we intentionally use bin, sbin and libdir patterns without prepending
    #  rpm_buildroot to catch all bindirs and libdirs everywhere
    #  I think it's ok, but maybe we'll need to reconsider down the road
    excl = ['/bin/', '/sbin/']
    excl.extend(PYTHON_LIBDIRS)

    for fname, config in configs.items():
        if fname != current:
            # we intentionally put whole dirs including rpm_buildroot into result
            if config.formatted_dict['default_for_rootdir']:
                excl.append(path_norm_join(rpm_buildroot, config.formatted_dict['rootdir']))
            excl.extend([path_norm_join(rpm_buildroot, d) \
                for d in config.formatted_dict['compile_dirs']])

    return sorted(excl)


def load_configs(location):
    """Loads and returns all configs from given location.

    Args:
        location: a directory to search for configs

    Returns:
        a mapping {config_name: ByteCompileConfig object, ...}
    """
    configs = {}
    for cf in glob.glob(path_norm_join(location, '*.conf')):
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
