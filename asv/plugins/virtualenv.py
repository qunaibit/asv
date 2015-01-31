# Licensed under a 3-clause BSD style license - see LICENSE.rst
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, unicode_literals, print_function

from distutils.version import LooseVersion
import inspect
import os

import six

from .. import environment
from ..console import log
from .. import util


class Virtualenv(environment.Environment):
    """
    Manage an environment using virtualenv.
    """
    tool_name = "virtualenv"

    def __init__(self, env_dir, python, executable, requirements, source_repo):
        """
        Parameters
        ----------
        env_dir : str
            Root path in which to cache environments on disk.

        python : str
            Version of Python.  Must be of the form "MAJOR.MINOR".

        executable : str
            Path to Python executable.

        requirements : dict
            Dictionary mapping a PyPI package name to a version
            identifier string.

        source_repo : Repo instance
            The source repo to use to install the project
        """
        self._executable = executable
        self._env_dir = env_dir
        self._python = python
        self._requirements = requirements
        self._path = os.path.abspath(os.path.join(
            self._env_dir, self.hashname))
        self._source_repo = source_repo

        try:
            import virtualenv
        except ImportError:
            raise util.UserError(
                "virtualenv must be installed to run asv with the given "
                "Python executable")

        # Can't use `virtualenv.__file__` here, because that will refer to a
        # .pyc file which can't be used on another version of Python
        self._virtualenv_path = os.path.abspath(
            inspect.getsourcefile(virtualenv))

        self._is_setup = False
        self._requirements_installed = False

    @classmethod
    def get_environments(cls, conf, python, repo):
        try:
            executable = util.which('python{0}'.format(python))
        except IOError:
            log.warn("No executable found for python {0}".format(python))
        else:
            for configuration in environment.iter_configuration_matrix(conf.matrix):
                yield cls(conf.env_dir, python, executable, configuration, repo)

    @classmethod
    def matches(self, python):
        try:
            import virtualenv
        except ImportError:
            return False
        else:
            if LooseVersion(virtualenv.__version__) == LooseVersion('1.11.0'):
                log.warn(
                    "asv is not compatible with virtualenv 1.11 due to a bug in "
                    "setuptools.")
            if LooseVersion(virtualenv.__version__) < LooseVersion('1.10'):
                log.warn(
                    "If using virtualenv, it much be at least version 1.10")

        try:
            util.which('python{0}'.format(python))
        except IOError:
            return False
        else:
            return True

    def setup(self):
        """
        Setup the environment on disk.  If it doesn't exist, it is
        created using virtualenv.  Then, all of the requirements are
        installed into it using `pip install`.
        """
        log.info("Creating virtualenv for {0}".format(self.name))
        util.check_call([
            self._executable,
            self._virtualenv_path,
            '--no-site-packages',
            self._path])

    def install_requirements(self):
        if self._requirements_installed:
            return

        self.create()

        self._run_executable('pip', ['install', '--upgrade',
                                     'setuptools'])

        if self._requirements:
            args = ['install', '--upgrade']
            for key, val in six.iteritems(self._requirements):
                if val is not None:
                    args.append("{0}=={1}".format(key, val))
                else:
                    args.append(key)
            self._run_executable('pip', args)

        self._requirements_installed = True

    def _run_executable(self, executable, args, **kwargs):
        return util.check_output([
            os.path.join(self._path, 'bin', executable)] + args, **kwargs)

    def install(self, package):
        log.info("Installing into {0}".format(self.name))
        self._run_executable('pip', ['install', package])

    def uninstall(self, package):
        log.info("Uninstalling {0} from {1}".format(package, self.name))
        self._run_executable('pip', ['uninstall', '-y', package],
                             valid_return_codes=None)

    def run(self, args, **kwargs):
        log.debug("Running '{0}' in {1}".format(' '.join(args), self.name))
        self.install_requirements()
        return self._run_executable('python', args, **kwargs)

    def _get_wheel_cache_path(self, commit_hash):
        """Get the wheel cache path corresponding to a given commit hash"""
        if commit_hash is None:
            return None

        path = os.path.join(self._wheel_cache_path, commit_hash)
        stamp = os.path.join(path, 'timestamp')
        if not os.path.isdir(path):
            os.makedirs(path)
        with open(stamp, 'wb'):
            pass
        return path

    def _get_wheel(self, commit_hash):
        cache_path = self._get_wheel_cache_path(commit_hash)
        if cache_path is None:
            return
        for fn in os.listdir(cache_path):
            if fn.endswith('.whl'):
                return os.path.join(cache_path, fn)
        return None

    def _cache_wheel(self, package, commit_hash):
        wheel = self._get_wheel(commit_hash)
        if wheel:
            return wheel

        cache_path = self._get_wheel_cache_path(commit_hash)
        if cache_path is None:
            return

        self._cleanup_wheel_cache()

        rel = os.path.relpath(package, os.getcwd())
        log.info("Building a wheel from {0} in {1}".format(rel, self.name))
        try:
            self._run_executable('pip', ['wheel', '--wheel-dir', cache_path,
                                         '--no-deps', '--no-index', package])
        except util.ProcessError:
            # failed -- clean up
            shutil.rmtree(cache_path)

        return self._get_wheel(commit_hash)

    def _cleanup_wheel_cache(self):
        if not os.path.isdir(self._wheel_cache_path):
            return

        def sort_key(name):
            path = os.path.join(self._wheel_cache_path, name,
                                'timestamp')
            try:
                return os.stat(path).st_mtime
            except OSError:
                return 0

        names = os.listdir(self._wheel_cache_path)
        names.sort(key=sort_key, reverse=True)

        for name in names[self._wheel_cache_size:]:
            path = os.path.join(self._wheel_cache_path, name)
            if os.path.isdir(path):
                shutil.rmtree(name)
