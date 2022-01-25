#!/usr/bin/env python3
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: nil; py-indent-offset: 4 -*-
# Coding Style: PEP8 - https://www.python.org/dev/peps/pep-0008/

# Python compatibility: 3.6+ - https://docs.python.org/3.6/
# This version of ssh-ident is developed for Python 3.6+. If it fails
# with earlier Python releases, then revert to original ssh-ident [v1].

# ssh-ident3 - Linux ssh wrapper to manage multiple identities
# Copyright (C) 2022  ssh-ident team - https://github.com/ssh-ident/
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.


##
## Import forward compatibility of Python 2.7 - no warranty that it works with Python 2.7 or Python
##
from __future__ import absolute_import, division, print_function, unicode_literals
#
import sys
if sys.version_info[0] <= 2:
    from future.builtins.disabled import *
    #
    from future import standard_library
    standard_library.install_aliases()
    #
    from builtins import *


##
## Meta data definitions: https://pypi.org/project/about/
##
__copyright__ = 'Copyright 2022, ssh-ident team'
__version__ = '0.1.0a1.dev' ## PEP440 & Semantic Versioning: https://www.python.org/dev/peps/pep-0440/, https://semver.org/
__status__ = 'Development'
__author__ = 'ssh-ident team'
__url__ = 'https://github.com/ssh-ident/'
__license__ = 'GPLv3'


##
## Standard imports
##
import os
import re
import json


##
## Version dependent imports and definitions
##

## 3.3+: shutil.which()
if (sys.version_info[0] > 3) \
or (sys.version_info[0] == 3 and sys.version_info[1] >= 3):
    import shutil
    def find_executable(cmd, path=None):
        return shutil.which(cmd, path=path)
else:
    import distutils.spawn
    def find_executable(executable, path=None):
        return distutils.spawn.find_executable(executable, path=path)


##
## Constants (use simple class, as enum is not available in vanilla Python 2.7)
##
class LOG_LEVEL():
    ## log levels
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4

    @classmethod
    def GetName(cls, value):
        if value == cls.ERROR:
            return '.'.join((cls.__name__, 'ERROR'))
        if value == cls.WARN:
            return '.'.join((cls.__name__, 'WARN'))
        if value == cls.INFO:
            return '.'.join((cls.__name__, 'INFO'))
        if value == cls.DEBUG:
            return '.'.join((cls.__name__, 'DEBUG'))
        return value


class CONFIG_ORIGIN():
    ENV = 'env'
    CONFIG = 'config'
    DEFAULT = 'default'
    ARGV = 'argv'


##
## Function replacements/extensions
##

## print extension (decorator style)
def extend_print_with_loglevel_and_prefix(original_print):
    def new_print(*args, **kwargs):
        ## Python 2.7 workaround for def new_print(*args, prefix=None, loglevel=LOG_LEVEL.INFO, **kwargs):
        prefix=None
        if 'prefix' in kwargs:
            prefix = kwargs['prefix']
            del kwargs['prefix']
        #
        loglevel=LOG_LEVEL.INFO
        if 'loglevel' in kwargs:
            loglevel = kwargs['loglevel']
            del kwargs['loglevel']

        ## Skip output if its log level is higher than the wanted verbosity level
        if loglevel > Config.verbosity:
            return None

        ## Skip output in batch mode
        if Config.ssh_batch_mode:
            return None

        ## Handle file and prefix arguments
        file = sys.stdout
        if prefix is None:
            if loglevel == LOG_LEVEL.ERROR:
                prefix = '[ERROR] '
                file = sys.stderr
            elif loglevel == LOG_LEVEL.WARN:
                prefix = '[Warn] '
            elif loglevel == LOG_LEVEL.DEBUG:
                prefix = '[debug] '
        #
        if 'file' in kwargs:
            file = kwargs['file']
        else:
            kwargs['file'] = file
        #
        if prefix:
            original_print(prefix, end='', file=file)

        result = original_print(*args, **kwargs)
        return result

    return new_print

print = extend_print_with_loglevel_and_prefix(print)


##
## Configuration Class
##
class Config(object):
    ## global settings related to log output
    verbosity = LOG_LEVEL.INFO
    ssh_batch_mode = False

    ## NOTE: a value can be defined everywhere, even if it does not make sense (e.g. BINARY_SSH in config)
    _defaults = {
        ## Configuration file
        'CONFIG_FILE': '.ssh-ident3.json',
        'CONFIG_DIRS': [
            '${XDG_CONFIG_HOME}',
            '~/.config',
            '~',
        ],

        ## Settings normally changed via environment
        'BINARY_SSH': None,
        'BINARY_SSH_AGENT': 'ssh-agent',
        'BINARY_SSH_ADD': 'ssh-add',

        ## Binary related settings
        'BINARY_DIR': None,

        ## Lists (not tuples) of special binaries
        'BINARIES_SSH_AGENT': ['ssh-agent', 'ssh-pageant'],
        'BINARIES_SSH_ADD': ['ssh-add'],
        'BINARIES_SSH_IDENT': ['ssh-ident3.py'],

        ## General settings
        'VERBOSITY': verbosity,
        'SSH_BATCH_MODE': ssh_batch_mode,
    }

    def __init__(self):
        self._values = {}

    def Load(self):
        config_file = os.path.normpath(self.GetValue('CONFIG_FILE'))
        config_dirs = self.GetValue('CONFIG_DIRS')
        for config_dir in config_dirs:
            ## Check if config file exists in config dir
            config_dir = os.path.normpath(os.path.expandvars(os.path.expanduser(config_dir)))
            if not os.path.isdir(config_dir):
                continue
            #
            config_path = os.path.join(config_dir, config_file)
            if not os.path.isfile(config_path):
                continue
            ## Load JSON file
            print('Loading config from {0}'.format(config_path), loglevel=LOG_LEVEL.DEBUG)
            with open(config_path) as file:
                config_json = file.read()
            config_json = re.sub('^\s*//.*$', '', config_json, flags=re.MULTILINE) ## empty javascript comment lines
            if config_json:
                self._values = json.loads(config_json)
                ## Convert constants
                if 'VERBOSITY' in self._values:
                    result = self._values['VERBOSITY']
                    if isinstance(result, str):
                        if not result.startswith('LOG_LEVEL.'):
                            result = ''.join(('LOG_LEVEL.', result))
                        result = eval(result)
                        self._values['VERBOSITY'] = result
            #
            break

    def GetDefaultEntry(self, parameter):
        result = None
        if parameter in self._defaults:
            result = [self._defaults[parameter], parameter, CONFIG_ORIGIN.DEFAULT]
            ## Add name of constants
            if parameter == 'VERBOSITY':
                result.append(LOG_LEVEL.GetName(result[0]))
        #
        return result

    def GetEntry(self, parameter):
        if parameter in os.environ:
            result = [os.environ[parameter], parameter, CONFIG_ORIGIN.ENV]
            ## Convert constants
            if parameter == 'VERBOSITY':
                if isinstance(result[0], str):
                    if not result[0].startswith('LOG_LEVEL.'):
                        result[0] = ''.join(('LOG_LEVEL.', result[0]))
                    result[0] = eval(result[0])
        elif parameter in self._values:
            result = [self._values[parameter], parameter, CONFIG_ORIGIN.CONFIG]
        elif parameter in self._defaults:
            result = [self._defaults[parameter], parameter, CONFIG_ORIGIN.DEFAULT]
        else:
            print(
                'Parameter "{0}" is not even defined in defaults. Check source code.'.format(parameter),
                loglevel=LOG_LEVEL.ERROR
            )
            sys.exit(2)
        ## Add name of constants
        if parameter == 'VERBOSITY':
            result.append(LOG_LEVEL.GetName(result[0]))
        #
        return result

    def GetValue(self, parameter):
        result = self.GetEntry(parameter)
        return result[0]

    def GetNames(self):
        return self._defaults.keys()


##
## Main routine as ssh-agent wrapper
##
def ssh_agent_wrapper(argv, main_binary):
    print('ssh-ident as ssh-agent wrapper',
        argv,
        'for', main_binary,
        loglevel=LOG_LEVEL.DEBUG,
    )


##
## Main routine as ssh-add wrapper
##
def ssh_add_wrapper(argv, main_binary):
    print('ssh-ident as ssh-add wrapper',
        argv,
        'for', main_binary,
        loglevel=LOG_LEVEL.DEBUG
    )


##
## Main routine as generic ssh wrapper
##
def ssh_wrapper(argv, main_binary):
    print('ssh-ident as (generic) ssh wrapper',
        argv,
        'for', main_binary,
        loglevel=LOG_LEVEL.DEBUG
    )


##
## Main routine as ssh-ident
##
def ssh_ident(argv):
    ## Reset verbosity if running as ssh-ident itself
    if Config.verbosity < LOG_LEVEL.INFO:
        Config.verbosity = LOG_LEVEL.INFO

    ## Analysis output for debugging
    print('ssh-ident runs as itself',
        argv,
        loglevel=LOG_LEVEL.DEBUG
    )

    ## Check arguments from command line
    import argparse

    description = '%(prog)s {version}  {copyright} {url}\n\
OpenSSH-compatible wrapper to manage multiple identities via ssh-agent/ssh-add.\n\
Licensed under {license}. This program comes with ABSOLUTELY NO WARRANTY.\n\
This is free software, and you are welcome to redistribute it under certain conditions.\n'\
        .format(
            copyright=__copyright__,
            version=__version__,
            status=__status__,
            author=__author__,
            url=__url__,
            license=__license__
        )

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-V', '--version', action='version', version=__version__)
    parser.add_argument('--config', '-c', action='store_true', help='show configuration')
    parser.add_argument('--identities', '-i', action='store_true', help='show identities')
    parser.add_argument('--origin', '-o', action='store_true', help='show origin of config and/or identity')
    parser.add_argument('--no-defaults', '-n', action='store_true', help='show no defaults of configuration')

    arguments = parser.parse_args()

    ## Show config
    if arguments.config:
        print('Configuration{0}:'.format(' changes' if arguments.no_defaults else ''))
        for config_name in sorted(config.GetNames()):
            config_entry = config.GetEntry(config_name)
            if arguments.no_defaults and config_entry[2] is CONFIG_ORIGIN.DEFAULT:
                continue
            config_value = config_entry[3] if len(config_entry) > 3 else config_entry[0]
            #
            extra_info = ''
            extra_sep = '  ## '
            if arguments.origin:
                extra_info = ''.join((extra_info, extra_sep, 'origin: {0}'.format(config_entry[2])))
                extra_sep = ', '
            if not(config_entry[2] is CONFIG_ORIGIN.DEFAULT):
                config_default = config.GetDefaultEntry(config_name)
                extra_info = ''.join((extra_info, extra_sep, '{0}: {1}'.format(CONFIG_ORIGIN.DEFAULT, json.dumps(config_default[3] if len(config_default) > 3 else config_default[0]))))
                extra_sep = ', '
            #
            print('"{0}": {1}{2}'
                .format(
                    config_name,
                    json.dumps(config_value),
                    extra_info
                )
            )
        print('^^^ Configuration end')

    ## TODO: Show identities (config? dirs? both?)
    if arguments.identities:
        print('Identities:')
        if arguments.origin:
            print('...with origin')
        print('^^^ Identities end')


##
## Globals (avoid if possible)
##
config = Config()


##
## Python main
##
if __name__ == '__main__':
    ## Load config
    ## Honor VERBOSITY and from environment before loading config
    Config.verbosity = config.GetValue('VERBOSITY')
    Config.ssh_batch_mode = config.GetValue('SSH_BATCH_MODE')
    config.Load()
    Config.verbosity = config.GetValue('VERBOSITY')
    Config.ssh_batch_mode = config.GetValue('SSH_BATCH_MODE')

    ## Detect main binary runtime name
    main_binary = config.GetEntry('BINARY_SSH')
    if not main_binary[0]:
        main_binary = [sys.argv[0], 'BINARY_SSH', CONFIG_ORIGIN.ARGV]
    main_binary.append(main_binary[0]) ## index 3: original value
    main_binary.append(os.path.abspath(os.path.normpath(main_binary[0]))) ## index 4: original value as absolute normalized path
    main_binary[0] = os.path.basename(main_binary[0])

    ## Run ssh-ident in correct mode for main binary runtime name
    if main_binary[0] in config.GetValue('BINARIES_SSH_IDENT'):
        ssh_ident(sys.argv)
    else:
        ## TODO: split here or handle all cases in one function?
        if main_binary[0] in config.GetValue('BINARIES_SSH_AGENT'):
            ssh_agent_wrapper(sys.argv, main_binary)
        elif main_binary[0] in config.GetValue('BINARIES_SSH_ADD'):
            ssh_add_wrapper(sys.argv, main_binary)
        else:
            ssh_wrapper(sys.argv, main_binary)
