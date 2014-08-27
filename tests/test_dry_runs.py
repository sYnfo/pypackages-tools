import os
import subprocess

import pytest

TEST_ROOTS = os.path.join(os.path.dirname(__file__), 'test_roots')
BYTECOMPILE_SCRIPT = 'brp-python-bytecompile.py'
BRP_PYTHON_BYTECOMPILE = os.path.join(os.path.dirname(__file__), '..', BYTECOMPILE_SCRIPT)


def run_bytecompile(pyruntime, directory, rpm_buildroot):
    proc = subprocess.Popen([pyruntime, BRP_PYTHON_BYTECOMPILE, '--dry-run', '--config-dir',
        os.path.join(TEST_ROOTS, directory, 'etc', 'pypackages-tools'), 'python', '1'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={'RPM_BUILD_ROOT': os.path.join(TEST_ROOTS, directory, rpm_buildroot)})

    out = proc.communicate()[0].decode('utf-8')
    return proc.returncode, out


def assert_libdirs_not_associated(retcode, output, libdirs, testdir, rpm_buildroot):
    """Warning: libdirs must not start with slash!"""
    assert retcode == 11
    assert BYTECOMPILE_SCRIPT + \
        ': Error: there are Python libdirs not associated with any Python runtime:' in output

    full_libdirs = [os.path.join(TEST_ROOTS, testdir, rpm_buildroot, l) for l in libdirs]
    for fl in full_libdirs:
        assert BYTECOMPILE_SCRIPT + ': ' + fl in output


def assert_multiple_default_root_pythons(retcode, output, root_pythons):
    assert retcode == 10
    assert BYTECOMPILE_SCRIPT + \
        ': Error, following roots are to be compiled by multiple Pythons:' in output

    check_str = '{bsc}: "{root}": {pythons}'
    for root, pythons in root_pythons.items():
        assert check_str.format(bsc=BYTECOMPILE_SCRIPT, root=root, pythons=', '.join(pythons)) \
            in output

def assert_compile_string(retcode, output, **kwargs):
    """This can be a bit fragile if there is some whitespace in the command..."""
    assert retcode == 0

    kwargs['to_compile'] = os.path.join(TEST_ROOTS, kwargs['to_compile'])
    flags_variations = ['', '-O']

    check_template = [BYTECOMPILE_SCRIPT + ': {python} {flags} -c \'import compileall, sys;',
        'sys.exit(not compileall.compile_dir("{to_compile}", {depth}, "{real_dir}", ',
        'force=1, quiet=1, rx={rx}))']

    for fv in flags_variations:
        kwargs['flags'] = fv
        check_string = ''.join(check_template).format(**kwargs)
        assert check_string in output

def test_no_config_for_libdirs(pyruntime):
    testdir = 'no_configs'
    rpm_buildroot = 'some/build/dir/BUILDROOT/foo-1.2.3.fcXY.x86_64'
    retcode, out = run_bytecompile(pyruntime, testdir, rpm_buildroot)
    assert_libdirs_not_associated(retcode, out, ['usr/lib/python2.7', 'usr/lib64/python8.9'],
        testdir, rpm_buildroot)


def test_conflicting_roots(pyruntime):
    testdir = 'conflicting_roots'
    rpm_buildroot = 'some/build/dir/BUILDROOT/foo-1.2.3.fcXY.x86_64'
    retcode, out = run_bytecompile(pyruntime, testdir, rpm_buildroot)
    assert_multiple_default_root_pythons(retcode, out,
        {'/': ['python2.7', 'python5.6', 'python8.9'], '/foo/bar': ['pythonXX', 'pythonYY']})

@pytest.mark.parametrize('has_default_python, testdir', [
    (True, 'one_libdir_and_default_python'),
    (False, 'one_libdir_no_default_python')
])
def test_one_libdir(pyruntime, has_default_python, testdir):
    rpm_buildroot = 'some/build/dir/BUILDROOT/foo-1.2.3.fcXY.x86_64'
    retcode, out = run_bytecompile(pyruntime, testdir, rpm_buildroot)

    assert 'Running from config "python2.7":' in out

    to_compile_base = os.path.join(testdir, rpm_buildroot)

    # first, test bytecompilation of the rootdir by default python
    python = '/usr/bin/python2.7'
    to_compile = to_compile_base
    rx="re.compile(r'/bin/|/sbin/|/usr/lib/python[0-9].[0-9]|/usr/lib64/python[0-9].[0-9]')"
    if has_default_python:
        assert_compile_string(retcode, out, python=python, depth=8, real_dir='/', rx=rx,
            to_compile=to_compile_base)

    # then test compilation of libdirs
    for real_dir, depth in [('/usr/lib/python2.7', 4), ('/usr/lib64/python2.7', 5)]:
        to_compile = to_compile_base + real_dir
        assert_compile_string(retcode, out, python=python, depth=depth, real_dir=real_dir, rx=None,
            to_compile=to_compile)

    # make sure that only the previously tested compile strings were printed
    assert out.count(BYTECOMPILE_SCRIPT + ':') == 7 if has_default_python else 5
