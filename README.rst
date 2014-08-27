pypackages-tools
================

This upstream is, in future, supposed to:

* replace brp-python-bytecompile script in RPM
* provide automatic dependency generators for Python packages
* provide general macros that will make Python packaging easier
* and generally contain various bits and pieces for RPM Python packaging (as done in Fedora)

brp-python-bytecompile.py
-------------------------

This script is supposed to be a replacement for ``brp-python-bytecompile`` bash script in RPM.
The significant improvement over the old bytecompile script is easy extensibility and easy
configuration. Unlike the old bytecompile script, this won't need overriding for new Python
environments/new SCLs/any other technology that would add new Python runtimes in RPMs to Fedora.

``brp-python-bytecompile.py`` script is one script that is fully configurable by configuration
files in ``/etc/pypackages-tools/``. An example config for a system default Python::

   [bytecompile]
   default_for_rootdir=1

This assumes that the file is called e.g. ``python2.7.conf`` - the ``python2.7`` value
is then used to construct meaningful defaults for other config values. Of course, the file
can be named differently or used to compile e.g. an SCL.

A list of all allowed configuration values with their meaning follows (the values allow
a certain form of string substitution using curly brackets value names, e.g. ``{python}``;
see below for more information on how that works):

* ``rootdir`` is the root directory for this Python, this only makes sense to change
  if specifying ``default_for_rootdir``
* ``default_for_rootdir`` tells the script to bytecompile files not only under ``compile_dirs``
  but also under all other directories in the buildroot, except ``compile_dirs`` of other
  configs and except other ``rootdirs``, that have their default Python
* ``flags`` specify the flags to invoke Python with for bytecompilation; should be left unmodified
* ``python`` path to Python interpreter to use for bytecompilation
* ``compile_dirs`` a colon separated list of directories to compile; usually, these will be
  Python libdirs, e.g. ``/usr/lib/python2.7:/usr/lib64/python2.7``
* ``inline_script`` is a script invoked from commandline like this:
  ``{python} {flags} -c '{inline_script}'``; should be left unmodified
* ``run`` is the actual invocation that is supposed to bytecompile a directory; it's
  usually run multiple times, so it's important to properly use the curly brackets value
  names in it, so that the script can reuse it for different types of compilation

This is an example of configuration for collection that contains Python 3.3::

   [bytecompile]
   rootdir=/opt/rh/{fname}/root/
   default_for_rootdir=1
   compile_dirs={rootdir}/usr/lib/python3.3:{rootdir}/usr/lib64/python3.3
   python={rootdir}/usr/bin/python3.3
   run=scl enable {fname} - <<EOF
           {python} {flags} -c '{inline_script}'
           EOF

The curly-braced strings, e.g. ``{rootdir}`` will get substituted with the referenced values.
The substitution works like this:

* ``fname`` is name of the configuration file, stripped of the extension, e.g. ``python33.conf``
  file will have ``fname`` of value ``python33``
* ``rootdir`` can use only ``{fname}`` value for substitution
* ``default_for_rootdir`` can be either ``1`` or ``0``
* ``flags`` (usually you shouldn't touch this) don't make use of any substitution
* ``python`` can use ``{rootdir}`` and ``{fname}`` for substitution
* ``compile_dirs`` can use ``{rootdir}``, ``{fname}`` and ``{python}`` for substitution
  (although using ``{python}`` usually doesn't make much sense)
* ``inline_script`` usually invokes ``compileall.compile_dir()`` method, so on top of of values
  above, it can also use values generated dynamically by the bytecompile script: ``{compile_dir}``
  (full path of the directory to compile, including RPM buildroot path), ``{depth}`` (depth of
  ``compile_dir``), ``{real_dir}`` (real directory location to hardcode to ``pyc`` and ``pyo``
  files) and ``{rx}`` (``None`` or regular expression that contains directories to omit when
  bytecompiling - these are passed when compiling the whole ``rootdir``)
* ``run`` is the whole invocation, can use any of the above values for substitution

Licensed under GPLv2+.
