#!/usr/bin/env python3
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: nil; py-indent-offset: 4 -*-
# Coding Style: PEP8 - https://www.python.org/dev/peps/pep-0008/

# Python compatibility: 3.6+ - https://docs.python.org/3.6/
# This version of ssh-ident is developed for Python 3.6+. If it fails
# with earlier Python releases, then revert to original ssh-ident[1].

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
import errno
import getpass
import json
import os
import re


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
    def get_name(cls, value):
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
    ARGV = 'argv'
    CONFIG = 'config'
    DEFAULT = 'defaults'
    DIR = 'dir'


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
    #
    CURRENT_USER_FALLBACK_DIR = '~/.ssh'

    ## NOTE: a value can be defined everywhere, even if it does not make sense (e.g. BINARY_SSH in config)
    ## NOTE: use lists [square brackets], not tuples (round brackets)
    _defaults = {
        ##
        ## Settings normally changed via environment
        ##

        ## Binary related settings
        'BINARY_SSH': None,
        'BINARY_SSH_AGENT': 'ssh-agent',
        'BINARY_SSH_ADD': 'ssh-add',

        ## General settings
        'VERBOSITY': verbosity,


        ##
        ## Settings normally changed via config file
        ##

        ## Binary related settings
        'BINARY_DIR': None,
        ## Options: [identities], [binaries], 'options'
        'SSH_OPTIONS': [
            [ [], ['ssh', 'scp', 'sftp', ], '-oUseRoaming=no'], ## reasonable default options
        ],
        'SSH_ADD_OPTIONS': [
            [ [], [], '-t 7200'], ## reasonable default options
        ],

        ## Names of special ssh binaries
        'BINARIES_SSH_AGENT': ['ssh-agent', 'ssh-pageant'],
        'BINARIES_SSH_ADD': ['ssh-add'],

        ## Where to find all the identities for the user
        'DIR_IDENTITIES': '${HOME}/.ssh/identities',
        'DEFAULT_IDENTITY': '${USER}',
        ## Binaries: [identities], 'binary'
        'IDENTITY_SSH_AGENT': [
        ],
        'IDENTITY_SSH_ADD': [
        ],

        ## Where to keep the information about each running agent
        'DIR_AGENTS': '${HOME}/.ssh/agents',


        ##
        ## Settings normally unchanged
        ##

        ## Configuration file
        'CONFIG_FILE': '.ssh-ident3.json',
        'CONFIG_DIRS': [
            '${XDG_CONFIG_HOME}',
            '~/.config',
            '~',
        ],

        ## Names of ssh-ident3 itself
        'BINARIES_SSH_IDENT': ['ssh-ident3.py'],

        ## General settings
        'SSH_BATCH_MODE': ssh_batch_mode,
    }

    def __init__(self):
        self._values = {}

    def load_config_file(self):
        config_file = os.path.normpath(self.get_value('CONFIG_FILE'))
        config_dirs = self.get_value('CONFIG_DIRS')
        for config_dir in config_dirs:
            ## Check if config file exists in config dir
            config_dir = os.path.normpath(config_dir)
            if not(os.path.isdir(config_dir)):
                continue
            #
            config_path = os.path.join(config_dir, config_file)
            if not(os.path.isfile(config_path)):
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
                        if not(result.startswith('LOG_LEVEL.')):
                            result = ''.join(('LOG_LEVEL.', result))
                        result = eval(result)
                        self._values['VERBOSITY'] = result
            #
            break

    @classmethod
    def _expand_value(cls, result):
        if isinstance(result['VALUE'], str):
            result['VALUE'] = os.path.expanduser(os.path.expandvars(result['VALUE']))
        elif isinstance(result['VALUE'], list):
            for index1, entry1 in enumerate(result['VALUE']):
                if isinstance(entry1, str):
                    result['VALUE'][index1] = os.path.expanduser(os.path.expandvars(entry1))
                elif isinstance(entry1, list):
                    for index2, entry2 in enumerate(entry1):
                        if isinstance(entry2, str):
                            entry1[index2] = os.path.expanduser(os.path.expandvars(entry2))
                        elif isinstance(entry2, list):
                            for index3, entry3 in enumerate(entry2):
                                if isinstance(entry3, str):
                                    entry2[index3] = os.path.expanduser(os.path.expandvars(entry3))

    def get_default_entry(self, setting, expand=True):
        result = None
        if setting in self._defaults:
            result = {
                'SETTING': setting,
                'ORIGIN': CONFIG_ORIGIN.DEFAULT,
                'UNEXPANDED': self._defaults[setting],
                'EXPAND': expand,
                'VALUE': self._defaults[setting],
            }
            if expand:
                Config._expand_value(result)
            ## Add name of constants
            if setting == 'VERBOSITY':
                result['NAME'] = LOG_LEVEL.get_name(result['VALUE'])
        #
        return result

    def get_entry(self, setting, expand=True):
        result = {
            'SETTING': setting,
            'EXPAND': expand,
        }
        if setting in os.environ:
            result['ORIGIN'] = CONFIG_ORIGIN.ENV
            result['VALUE'] = result['UNEXPANDED'] = os.environ[setting]
            ## Convert constants
            if setting == 'VERBOSITY':
                if isinstance(result['VALUE'], str):
                    if not(result['VALUE'].startswith('LOG_LEVEL.')):
                        result['VALUE'] = ''.join(('LOG_LEVEL.', result['VALUE']))
                    result['VALUE'] = eval(result['VALUE'])
        elif setting in self._values:
            result['ORIGIN'] = CONFIG_ORIGIN.CONFIG
            result['VALUE'] = result['UNEXPANDED'] = self._values[setting]
        elif setting in self._defaults:
            result['ORIGIN'] = CONFIG_ORIGIN.DEFAULT
            result['VALUE'] = result['UNEXPANDED'] = self._defaults[setting]
        else:
            print(
                'Setting "{0}" is not even defined in defaults. Check source code.'.format(setting),
                loglevel=LOG_LEVEL.ERROR
            )
            sys.exit(2)
        if expand:
            Config._expand_value(result)
        ## Add name of constants
        if setting == 'VERBOSITY':
            result['NAME'] = LOG_LEVEL.get_name(result['VALUE'])
        #
        return result

    def get_value(self, setting, expand=True):
        result = self.get_entry(setting, expand)
        return result['VALUE']

    def get_setting_names(self):
        return self._defaults.keys()


##
## Main routine as ssh-agent wrapper
##
def ssh_agent_wrapper(argv, main_binary):
    print('ssh-ident3 runs as ssh-agent wrapper',
        argv,
        'for', main_binary,
        loglevel=LOG_LEVEL.DEBUG,
    )


##
## Main routine as ssh-add wrapper
##
def ssh_add_wrapper(argv, main_binary):
    print('ssh-ident3 runs as ssh-add wrapper',
        argv,
        'for', main_binary,
        loglevel=LOG_LEVEL.DEBUG
    )


##
## Main routine as generic ssh wrapper
##
def ssh_wrapper(argv, main_binary):
    print('ssh-ident3 runs as (generic) ssh wrapper',
        argv,
        'for', main_binary,
        loglevel=LOG_LEVEL.DEBUG
    )


##
## Main routine as ssh-ident
##
def ssh_ident(argv):
    ## Reset verbosity if running as ssh-ident3 itself
    if Config.verbosity < LOG_LEVEL.INFO:
        Config.verbosity = LOG_LEVEL.INFO

    ## Analysis output for debugging
    print('ssh-ident3 runs as itself',
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
    parser.add_argument('--origin', '-o', action='store_true', help='show origin of configuration settings')
    parser.add_argument('--modified', '-m', action='store_true', help='show only modified settings of configuration')
    parser.add_argument('--defaults', '-d', action='store_true', help='show default for modified setting')

    arguments = parser.parse_args()

    ## Show config
    if arguments.config:
        print('Configuration{0}:'.format(' modifications' if arguments.modified else ''))
        for config_name in sorted(config.get_setting_names()):
            config_entry = config.get_entry(config_name, expand=False)
            if arguments.modified and config_entry['ORIGIN'] is CONFIG_ORIGIN.DEFAULT:
                continue
            #
            if arguments.defaults and not(config_entry['ORIGIN'] is CONFIG_ORIGIN.DEFAULT):
                config_default = config.get_default_entry(config_name, expand=False)
                if config_entry['VALUE'] != config_default['VALUE']:
                    config_value = config_default['NAME'] if 'NAME' in config_default else config_default['VALUE']
                    print('// default {0}: {1}'
                        .format(
                            json.dumps(config_name, ensure_ascii=False),
                            json.dumps(config_value, ensure_ascii=False)
                        )
                    )
            #
            config_value = config_entry['NAME'] if 'NAME' in config_entry else config_entry['VALUE']
            extra_info = ''
            extra_sep = '  ## '
            if arguments.origin:
                extra_info = ''.join((extra_info, extra_sep, 'origin: {0}'.format(config_entry['ORIGIN'])))
                extra_sep = ', '
            print('{0}: {1}{2}'
                .format(
                    json.dumps(config_name, ensure_ascii=False),
                    json.dumps(config_value, ensure_ascii=False),
                    extra_info
                )
            )
        print('^^^^^ Configuration end')

    ## Show identities
    if arguments.identities:
        def add_identity(identity, identities, config_entry):
            expanded_identity = os.path.expanduser(os.path.expandvars(identity))
            origin = config_entry['ORIGIN']
            print('Identity:', identity, expanded_identity, origin, config_entry['SETTING'], loglevel=LOG_LEVEL.DEBUG)
            if not(expanded_identity in identities):
                identities[expanded_identity] = {}
                identities[expanded_identity]['ORIGIN'] = origin
                identities[expanded_identity]['SETTING'] = config_entry['SETTING']
                identities[expanded_identity]['UNEXPANDED'] = identity
            else:
                old_origin = identities[expanded_identity]['ORIGIN']
                if (origin is CONFIG_ORIGIN.ENV
                  and not(old_origin is CONFIG_ORIGIN.ENV)) \
                or (origin is CONFIG_ORIGIN.ARGV \
                  and not(old_origin is CONFIG_ORIGIN.ENV)) \
                or (origin is CONFIG_ORIGIN.CONFIG \
                  and not(old_origin is CONFIG_ORIGIN.ARGV) \
                  and not(old_origin is CONFIG_ORIGIN.ENV)) \
                or (origin is CONFIG_ORIGIN.DEFAULT \
                  and not(old_origin is CONFIG_ORIGIN.CONFIG) \
                  and not(old_origin is CONFIG_ORIGIN.ARGV) \
                  and not(old_origin is CONFIG_ORIGIN.ENV)):
                    identities[expanded_identity]['ORIGIN'] = origin
                    identities[expanded_identity]['SETTING'] = config_entry['SETTING']
            if origin is CONFIG_ORIGIN.DIR:
                identities[expanded_identity]['DIR'] = config_entry['VALUE']

        print('Identities:')
        identities = {}
        ## Determine identities from configuration
        for config_name in ['DEFAULT_IDENTITY']:
            config_entry = config.get_entry(config_name, expand=False)
            identity = config_entry['VALUE']
            add_identity(identity, identities, config_entry)
        for config_name in ['SSH_OPTIONS', 'SSH_ADD_OPTIONS', 'IDENTITY_SSH_AGENT', 'IDENTITY_SSH_ADD']:
            config_entry = config.get_entry(config_name, expand=False)
            for config_list in config_entry['VALUE']:
                for identity in config_list[0]:
                    add_identity(identity, identities, config_entry)
        ## Determine identities from directory
        config_entry = config.get_entry('DIR_IDENTITIES')
        identities_dir = os.path.normpath(config_entry['VALUE'])
        if os.path.isdir(identities_dir):
            try:
                dir_entries_list = os.listdir(identities_dir)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            config_entry = {
                'SETTING': 'directory',
                'ORIGIN': CONFIG_ORIGIN.DIR,
            }
            for identity in dir_entries_list:
                config_entry['VALUE'] = os.path.join(identities_dir, identity)
                if os.path.isdir(config_entry['VALUE']):
                    add_identity(identity, identities, config_entry)
        ## Special case current user
        identity = getpass.getuser()
        if identity in identities:
            if not('dir' in identities[identity]):
                config_entry = {
                    'SETTING': 'directory',
                    'ORIGIN': CONFIG_ORIGIN.DIR,
                    'VALUE': os.path.expanduser(Config.CURRENT_USER_FALLBACK_DIR),
                }
                if os.path.isdir(config_entry['VALUE']):
                    add_identity(identity, identities, config_entry)

        ## Display identities
        for identity in sorted(identities.keys()):
            extra_info = ''
            extra_sep = ''
            if not('DIR' in identities[identity]):
                extra_info = ''.join((extra_info, extra_sep, 'MISSING directory'))
                extra_sep = ', '
            else:
                if identities[identity]['ORIGIN'] is CONFIG_ORIGIN.DIR:
                    extra_info = ''.join((extra_info, extra_sep, 'not referenced in config'))
                    extra_sep = ', '
                extra_info = ''.join((extra_info, extra_sep, identities[identity]['DIR']))
                extra_sep = ', '
            #
            if not(identities[identity]['ORIGIN'] is CONFIG_ORIGIN.DIR):
                extra_info = ''.join((extra_info, extra_sep, 'referenced in {0} via {1}'.format(identities[identity]['ORIGIN'], json.dumps(identities[identity]['UNEXPANDED'], ensure_ascii=False))))
                extra_sep = ', '
            #
            print('{0}: {1}'
                .format(
                    json.dumps(identity, ensure_ascii=False),
                    extra_info
                )
            )
        print('^^^^^ Identities end')


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
    Config.verbosity = config.get_value('VERBOSITY')
    Config.ssh_batch_mode = config.get_value('SSH_BATCH_MODE')
    config.load_config_file()
    ## TODO: check settings
    Config.verbosity = config.get_value('VERBOSITY')
    Config.ssh_batch_mode = config.get_value('SSH_BATCH_MODE')

    ## Detect main binary runtime name
    main_binary = config.get_entry('BINARY_SSH')
    if not(main_binary['VALUE']):
        main_binary['VALUE'] = main_binary['UNEXPANDED'] = sys.argv[0]
        main_binary['ORIGIN'] = CONFIG_ORIGIN.ARGV
    main_binary['ORIGINAL_VALUE'] = main_binary['VALUE'] ## original value
    main_binary['ABSOLUTE_PATH'] = os.path.abspath(os.path.normpath(main_binary['VALUE'])) ## original value as absolute normalized path
    main_binary['VALUE'] = main_binary['UNEXPANDED'] = os.path.basename(main_binary['VALUE'])

    ## Run ssh-ident3 in correct mode for main binary runtime name
    if main_binary['VALUE'] in config.get_value('BINARIES_SSH_IDENT'):
        ssh_ident(sys.argv)
    else:
        ## TODO: split here or handle all cases in one function?
        if main_binary['VALUE'] in config.get_value('BINARIES_SSH_AGENT'):
            ssh_agent_wrapper(sys.argv, main_binary)
        elif main_binary['VALUE'] in config.get_value('BINARIES_SSH_ADD'):
            ssh_add_wrapper(sys.argv, main_binary)
        else:
            ssh_wrapper(sys.argv, main_binary)
