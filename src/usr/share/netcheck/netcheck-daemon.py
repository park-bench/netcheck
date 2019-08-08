#!/usr/bin/env python3

# Copyright 2015-2019 Joel Allen Luellwitz and Emily Frost
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

__author__ = 'Joel Luellwitz and Emily Frost'
__version__ = '0.8'

import logging
import signal
import sys
import traceback
import configparser
import daemon
from lockfile import pidlockfile
from parkbenchcommon import confighelper
from parkbenchcommon import broadcaster
import netcheck

PID_FILE = '/run/netcheck.pid'
PROGRAM_UMASK = 0o022 # rw-r--r-- and drwxr-xr-x

# Verify config file here.

config_file = configparser.SafeConfigParser()
config_file.read('/etc/netcheck/netcheck.conf')

# Get logging options first.
config_helper = confighelper.ConfigHelper()
log_file = config_helper.verify_string_exists(config_file, 'log_file')
log_level = config_helper.verify_string_exists(config_file, 'log_level')

# Configure the logger.
config_helper.configure_logger(log_file, log_level)
logger = logging.getLogger()

# Now read the rest of them.
config = {}
config['connection_ids'] = config_helper.verify_string_list_exists(
    config_file, 'connection_ids')
config['nameservers'] = config_helper.verify_string_list_exists(
    config_file, 'nameservers')
if len(config['nameservers']) < 2:
    message = "At least two nameservers are required."
    logger.critical(message)
    raise confighelper.ValidationException(message)
config['dns_queries'] = config_helper.verify_string_list_exists(
    config_file, 'dns_queries')
if len(config['dns_queries']) < 2:
    message = "At least two domain names are required."
    logger.critical(message)
    raise confighelper.ValidationException(message)

config['dns_timeout'] = config_helper.verify_number_exists(config_file, 'dns_timeout')
config['connection_activation_timeout'] = config_helper.verify_number_within_range(
    config_file, 'connection_activation_timeout', lower_bound=0)
config['connection_periodic_check_time'] = config_helper.verify_number_within_range(
    config_file, 'connection_periodic_check_time', lower_bound=0)
config['available_connections_check_time'] = config_helper.verify_number_within_range(
    config_file, 'available_connections_check_time', lower_bound=0)

config['required_usage_connection_ids'] = config_helper.get_string_list_if_exists(
    config_file, 'required_usage_connection_ids')
config['required_usage_max_delay'] = config_helper.verify_number_within_range(
    config_file, 'required_usage_max_delay', lower_bound=0)
config['required_usage_failed_retry_delay'] = config_helper.verify_number_within_range(
    config_file, 'required_usage_failed_retry_delay', lower_bound=0)

config['main_loop_delay'] = config_helper.verify_number_within_range(
    config_file, 'main_loop_delay', lower_bound=0)
config['periodic_status_delay'] = config_helper.verify_number_within_range(
    config_file, 'periodic_status_delay', lower_bound=0)


def sig_term_handler(signal, stack_frame):
    """Quit when SIGTERM is received."""
    logger.info('Received SIGTERM, quitting.')
    sys.exit(0)

signal.signal(signal.SIGTERM, sig_term_handler)

try:
    log_file_handle = config_helper.get_log_file_handle()

    daemon_context = daemon.DaemonContext(
        working_directory='/',
        pidfile=pidlockfile.PIDLockFile(PID_FILE),
        umask=PROGRAM_UMASK
        )

    daemon_context.signal_map = {
        signal.SIGTERM: sig_term_handler
        }

    daemon_context.files_preserve = [log_file_handle]
    # TODO: Change uid and gid to the netcheck user before merging in standard-daemonizing.
    broadcaster = broadcaster.Broadcaster(
        program_name='netcheck', broadcast_name='gateway-changed', uid=0, gid=0)

    logger.info('Daemonizing...')
    with daemon_context:
        logger.info('Initializing NetCheck.')
        the_checker = netcheck.NetCheck(config, broadcaster)
        the_checker.start()

except Exception as exception:
    logger.critical('%s: %s', type(exception).__name__, str(exception))
    logger.critical(traceback.format_exc())
    raise
