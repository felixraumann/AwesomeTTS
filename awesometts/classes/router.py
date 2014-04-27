# -*- coding: utf-8 -*-

# AwesomeTTS text-to-speech add-on for Anki
#
# Copyright (C) 2014       Anki AwesomeTTS Development Team
# Copyright (C) 2014       Dave Shifflett
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Dispatch management of available services
"""

__all__ = ['Router']

import os.path
from PyQt4 import QtCore, QtGui

from .services import Trait as BaseTrait


_SIGNAL = QtCore.SIGNAL('awesomeTtsThreadDone')

_PREFIXED = lambda prefix, lines: "\n".join(
    prefix + line
    for line in (lines if isinstance(lines, list) else lines.split("\n"))
)


class Router(object):
    """
    Allows the registration, lookup, and routing of concrete Service
    implementations.

    By having a routing-like object sit in-between the UI and the actual
    service code, Service implementations can be lazily loaded and their
    results can be cached, transparently to both sides.

    Additionally, some methods on the router offer callbacks. In this
    case, if the method is going to call a service that might block,
    then the method can arrange for that call to occur on a different
    thread and then call the callback when done. Otherwise, the callback
    can be called immediately with neither blocking nor threading.

    All methods in this class that take a callback do NOT raise
    exceptions directly, but rather pass exceptions to the callback.
    """

    Trait = BaseTrait

    class BusyError(RuntimeError):
        """Raised for requests for files that are already underway."""

    __slots__ = [
        '_busy',       # list of file paths that are in-progress
        '_cache_dir',  # path for writing cached media files
        '_logger',     # logger-like interface with debug(), info(), etc.
        '_pool',       # instance of the _Pool class for managing threads
        '_services',   # bundle with aliases, avail, lookup
    ]

    def __init__(self, services, cache_dir, logger):
        """
        The services should be a bundle with the following:

            - mappings (list of tuples): each with service ID, class
            - aliases (list of tuples): alternate-to-official service IDs
            - normalize (callable): for service IDs and option keys
            - textize (callable): for sanitizing human input text
            - args (tuple): to be passed to Service constructors
            - kwargs (dict): to be passed to Service constructors

        The cache directory should be one where media files get stored
        for a semi-permanent time.

        The logger object should have an interface like the one used by
        the standard library logging module, with debug(), info(), and
        so on, available.
        """

        services.aliases = {
            services.normalize(from_svc_id): services.normalize(to_svc_id)
            for from_svc_id, to_svc_id in services.aliases
        }

        services.avail = None

        services.lookup = {
            services.normalize(svc_id): {
                'class': svc_class,
                'name': svc_class.NAME or svc_id,
                'traits': svc_class.TRAITS or [],
            }
            for svc_id, svc_class in services.mappings
        }

        self._busy = []
        self._cache_dir = cache_dir
        self._logger = logger
        self._pool = _Pool()
        self._services = services

    def by_trait(self, trait):
        """
        Returns a list of service names that advertise the given trait.
        """

        return [
            service['name']
            for service
            in self._services.lookup.values()
            if trait in service['traits']
        ]

    def get_services(self):
        """
        Returns available services.
        """

        if not self._services.avail:
            self._logger.debug("Building the list of services...")

            for service in self._services.lookup.values():
                self._load_service(service)

            self._services.avail = sorted([
                (svc_id, service['name'])
                for svc_id, service in self._services.lookup.items()
                if service['instance']
            ], key=lambda (svc_id, text): text.lower())

        return self._services.avail

    def get_desc(self, svc_id):
        """
        Returns the description associated with the service.
        """

        svc_id, service = self._fetch_service(svc_id)

        if 'desc' not in service:
            self._logger.debug(
                "Retrieving the description for %s",
                service['name'],
            )
            service['desc'] = service['instance'].desc()

        return service['desc']

    def get_options(self, svc_id):
        """
        Returns a list of options that should be displayed for the
        service, with defaults highlighted.
        """

        svc_id, service = self._fetch_options(svc_id)

        return service['options']

    def __call__(self, svc_id, text, options, callbacks):
        """
        Given the service ID and associated options, pass the text into
        the service for processing.

        The callbacks parameter is a dict and contains the following:

            - 'done' (optional): called as soon as the call is complete
            - 'okay' (required): called with a path to the media file
            - 'fail' (required): called with an exception for validation
               errors or failed service calls occurs

        Because it is asynchronous in nature, this method does not raise
        exceptions normally; they are passed to callbacks['fail'].

        "Exceptions" to that rule:

            - an AssertionError is raised the caller failed to supply
              the required callbacks
            - an exception could be theoretically be raised if the
              threading subsystem failed
        """

        assert 'done' not in callbacks or callable(callbacks['done'])
        assert 'okay' in callbacks and callable(callbacks['okay'])
        assert 'fail' in callbacks and callable(callbacks['fail'])

        try:
            self._logger.debug(
                "Call for '%s' w/ %s\n%s",
                svc_id, options, _PREFIXED("<<< ", text),
            )

            text = self._validate_text(text)
            svc_id, service, options = self._validate_service(svc_id, options)
            path = self._validate_path(svc_id, text, options)
            cache_hit = os.path.exists(path)

            self._logger.debug(
                "Parsed call to '%s' w/ %s and \"%s\" at %s (cache %s)",
                svc_id, options, text, path, "hit" if cache_hit else "miss",
            )

        except StandardError as exception:
            if 'done' in callbacks:
                callbacks['done']()
            callbacks['fail'](exception)

            return

        if cache_hit:
            if 'done' in callbacks:
                callbacks['done']()
            callbacks['okay'](path)

        else:
            self._busy.append(path)
            self._pool.spawn(
                task=lambda: service['instance'].run(text, options, path),
                callback=lambda exception: (
                    self._busy.remove(path),
                    'done' in callbacks and callbacks['done'](),
                    exception and callbacks['fail'](exception) or
                        callbacks['okay'](path),
                )
            )

    def _validate_text(self, text):
        """
        Normalize the text and return it. If after normalization, the
        text is empty, raises a ValueError.
        """

        text = self._services.textize(text)
        if not text:
            raise ValueError("The input text must be set.")

        return text

    def _validate_service(self, svc_id, options):
        """
        Finds the given service ID, normalizes the text, and validates
        the options, returning the following:

            - 0th: normalized service ID
            - 1st: service lookup dict
            - 2nd: normalized text
            - 3rd: options, normalized and defaults filled in
            - 4th: cache path
        """

        svc_id, service = self._fetch_options(svc_id)
        svc_options = service['options']
        svc_options_keys = [svc_option['key'] for svc_option in svc_options]

        options = {
            key: value
            for key, value in [
                (self._services.normalize(key), value)
                for key, value in options.items()
            ]
            if key in svc_options_keys
        }

        problems = self._validate_options(options, svc_options)
        if problems:
            raise ValueError(
                "Running the '%s' (%s) service failed: %s." %
                (svc_id, service['name'], "; ".join(problems))
            )

        return svc_id, service, options

    def _validate_options(self, options, svc_options):
        """
        Attempt to normalize and validate the passed options in-place,
        given the official svc_options.

        Returns a list of problems, if any.
        """

        problems = []

        for svc_option in svc_options:
            key = svc_option['key']

            if key in options:
                try:
                    # transform is inside try as it might throw a ValueError
                    transformed_value = svc_option['transform'](options[key])

                    if isinstance(svc_option['values'], tuple):
                        if (
                            transformed_value < svc_option['values'][0] or
                            transformed_value > svc_option['values'][1]
                        ):
                            raise ValueError("outside of %d..%d" % (
                                svc_option['values'][0],
                                svc_option['values'][1],
                            ))

                    else:  # list of tuples
                        next(
                            True
                            for item in svc_option['values']
                            if item[0] == transformed_value
                        )

                    options[key] = transformed_value

                except ValueError as exception:
                    problems.append(
                        "invalid value '%s' for '%s' attribute (%s)" %
                        (options[key], key, exception.message)
                    )

                except StopIteration:
                    problems.append(
                        "'%s' is not an option for '%s' attribute (try %s)" %
                        (
                            options[key], key,
                            ", ".join(v[0] for v in svc_option['values']),
                        )
                    )

            elif 'default' in svc_option:
                options[key] = svc_option['default']

            else:
                problems.append("'%s' attribute is required" % key)

        self._logger.debug(
            "Validated and normalized '%s' with failure count of %d",
            "', '".join(svc_option['key'] for svc_option in svc_options),
            len(problems),
        )

        return problems

    def _validate_path(self, svc_id, text, options):
        """
        Given the service ID, its associated options, and the desired
        text, generate a cache path. If the file is already being
        processed, raise a BusyError.
        """

        path = self._path_cache(svc_id, text, options)
        if path in self._busy:
            raise self.BusyError(
                "The '%s' service is already busy processing %s." %
                (svc_id, path)
            )

        return path

    def _fetch_options(self, svc_id):
        """
        Identifies the service by its ID, checks to see if the options
        list need construction, and then return back the normalized ID
        and service lookup dict.
        """

        svc_id, service = self._fetch_service(svc_id)

        if 'options' not in service:
            self._logger.debug(
                "Building the options list for %s",
                service['name'],
            )

            service['options'] = []

            for option in service['instance'].options():
                assert 'key' in option, "missing option key for %s" % svc_id
                assert self._services.normalize(option['key']) == \
                    option['key'], "bad %s key %s" % (svc_id, option['key'])
                assert 'label' in option, \
                    "missing %s label for %s" % (option['key'], svc_id)
                assert 'values' in option, \
                    "missing %s values for %s" % (option['key'], svc_id)
                assert isinstance(option['values'], list) or \
                    isinstance(option['values'], tuple) and \
                    len(option['values']) in range(2, 4), \
                    "%s values for %s should be list or 2-3-tuple" % \
                    (option['key'], svc_id)
                assert 'transform' in option, \
                    "missing %s transform for %s" % (option['key'], svc_id)

                if not option['label'].endswith(":"):
                    option['label'] += ":"

                if 'default' in option and isinstance(option['values'], list):
                    option['values'] = [
                        item if item[0] != option['default']
                        else (item[0], item[1] + " [default]")
                        for item in option['values']
                    ]

                service['options'].append(option)

        return svc_id, service

    def _fetch_service(self, svc_id):
        """
        Finds the service using the svc_id, normalizing it and using the
        aliases list, initializes if this is its first use, and returns
        the normalized svc_id and service lookup dict.

        Raises KeyError if a bad svc_id is passed.

        Raises EnvironmentError if a good svc_id is passed, but the
        given service is not available for this session.
        """

        svc_id = self._services.normalize(svc_id)
        if svc_id in self._services.aliases:
            svc_id = self._services.aliases[svc_id]

        try:
            service = self._services.lookup[svc_id]
        except KeyError:
            raise ValueError("There is no '%s' service" % svc_id)

        self._load_service(service)

        if not service['instance']:
            raise EnvironmentError(
                "The %s service is not currently available" %
                service['name']
            )

        return svc_id, service

    def _load_service(self, service):
        """
        Given a service lookup dict, tries to initialize the service if
        it is not already initialized. Exceptions are trapped and logged
        with the 'instance' then set to None. Successful initializations
        set the 'instance' to the resulting object.
        """

        if 'instance' in service:
            return

        self._logger.info("Initializing %s service...", service['name'])

        try:
            service['instance'] = service['class'](
                *self._services.args,
                **self._services.kwargs
            )

            self._logger.info("%s service initialized", service['name'])

        except StandardError:
            service['instance'] = None  # flag this service as unavailable

            from traceback import format_exc
            trace_lines = format_exc().split('\n')

            self._logger.warn(
                "Initialization failed for %s service\n%s",
                service['name'],
                _PREFIXED("!!! ", trace_lines),
            )

    def _path_cache(self, svc_id, text, options):
        """
        Returns a consistent cache path given the svc_id, text, and
        options. This can be used to repeat the same request yet reuse
        the same path.
        """

        hash_input = '/'.join([
            text,
            svc_id,
            ';'.join(
                '='.join([key, str(value)])
                for key, value
                in sorted(options.items())
            )
        ])

        from hashlib import sha1
        return os.path.join(
            self._cache_dir,
            '.'.join([
                '-'.join([
                    svc_id,
                    sha1(
                        hash_input.encode('utf-8')
                        if isinstance(hash_input, unicode)
                        else hash_input
                    ).hexdigest(),
                ]),
                'mp3',
            ]),
        )


class _Pool(QtGui.QWidget):
    """
    Managers a pool of worker threads to keep the UI responsive.
    """

    __slots__ = [
        '_next_id',    # the next ID we will use
        '_callbacks',  # mapping of IDs to the desired callbacks
        '_workers',    # mapping of IDs to worker instances
    ]

    def __init__(self):
        """
        Initialize my internal state (next ID and lookup pools for the
        callbacks and workers).
        """

        super(_Pool, self).__init__()

        self._next_id = 0
        self._callbacks = {}
        self._workers = {}

    def spawn(self, task, callback):
        """
        Create a worker thread for the given task. When the thread
        completes, the callback will be called.
        """

        self._next_id += 1
        self._callbacks[self._next_id] = callback
        self._workers[self._next_id] = _Worker(self._next_id, task)

        self.connect(self._workers[self._next_id], _SIGNAL, self._on_signal)

        self._workers[self._next_id].start()

    def _on_signal(self, worker_id, exception):
        """
        When the worker thread finishes, execute its callback and clean
        up references to it.
        """

        self._callbacks[worker_id](exception)

        del self._callbacks[worker_id]
        del self._workers[worker_id]


class _Worker(QtCore.QThread):
    """
    Generic worker for running processes in the background.
    """

    __slots__ = [
        '_id',     # my worker ID; used to communicate back to main thread
        '_task',   # the task I will need to call when run
    ]

    def __init__(self, worker_id, task):
        """
        Save my worker ID and task.
        """

        super(_Worker, self).__init__()

        self._id = worker_id
        self._task = task

    def run(self):
        """
        Run my assigned task. If an exception is raised, pass it back to
        the main thread via the callback.
        """

        try:
            self._task()
        except StandardError as exception:
            self.emit(_SIGNAL, self._id, exception)
            return

        self.emit(_SIGNAL, self._id, None)
