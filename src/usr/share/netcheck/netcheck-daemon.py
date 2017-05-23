#!/usr/bin/env python2

# Copyright 2015-2016 Joel Allen Luellwitz and Andrew Klapp
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

import confighelper
import ConfigParser
import daemon
import logging
import netcheck
import os
import signal
import sys
import traceback

pid_file = '/run/netcheck.pid'

# TODO: Consider running in a chroot or jail.

# Verify config file here.

config_file = ConfigParser.SafeConfigParser()
config_file.read('/etc/netcheck/netcheck.conf')

# Get logging options first.
config_helper = confighelper.ConfigHelper()
log_file = config_helper.verify_string_exists_prelogging(config_file, 'log_file')
log_level = config_helper.verify_string_exists_prelogging(config_file, 'log_level')

# Configure the logger.
config_helper.configure_logger(log_file, log_level)
logger = logging.getLogger()

# Now read the rest of them.
config = {}
config['dig_timeout'] = config_helper.verify_number_exists(config_file, 'dig_timeout')
config['nmcli_timeout'] = config_helper.verify_number_exists(config_file, 'nmcli_timeout')
config['sleep_range'] = config_helper.verify_number_exists(config_file, 'sleep_range')

config['wired_network_name'] = config_helper.verify_string_exists(config_file, 'wired_network_name')
config['wifi_network_names'] = config_helper.verify_string_exists(config_file, 'wifi_network_names').split(',')
config['nameservers'] = config_helper.verify_string_exists(config_file, 'nameservers').split(',')
config['dns_queries'] = config_helper.verify_string_exists(config_file, 'dns_queries').split(',')

config['backup_network_name'] = config_helper.verify_string_exists(config_file, 'backup_network_name')
config['backup_network_max_usage_delay'] = \
        config_helper.verify_number_exists(config_file, 'backup_network_max_usage_delay')
config['backup_network_failed_max_usage_delay'] = \
        config_helper.verify_number_exists(config_file, 'backup_network_failed_max_usage_delay')

# Quit when SIGTERM is received
def sig_term_handler(signal, stack_frame):
    logger.info("Received SIGTERM, quitting.")
    sys.exit(0)

# TODO: Work out a permissions setup so that this program doesn't run as root.
daemon_context = daemon.DaemonContext(
    working_directory = '/',
    pidfile = pidlockfile.PIDLockFile(pid_file),
    umask = 0
    )

daemon_context.signal_map = {
    signal.SIGTERM : sig_term_handler
    }

with daemon_context:
    try:
        the_checker = netcheck.NetCheck(config)
        the_checker.check_loop()

    except Exception as e:
        logger.critical("%s: %s\n" % (type(e).__name__, e.message))
        logger.error(traceback.format_exc())
        sys.exit(1)
