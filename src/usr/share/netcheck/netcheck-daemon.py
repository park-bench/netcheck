#!/usr/bin/env python2

# Copyright 2015-2017 Joel Allen Luellwitz and Andrew Klapp
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
import logging
import netcheck
import os
import signal
import sys
import traceback

PID_FILE = '/run/netcheck.pid'


# TODO: Use standard daemonize module.
def daemonize():
    # Fork the first time to make init our parent.
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        logger.critical('Failed to make parent process init: %d (%s)' %
                        (e.errno, e.strerror))
        sys.exit(1)

    # TODO: Lock this down.
    os.chdir('/')  # Change the working directory
    os.setsid()  # Create a new process session.
    os.umask(0)

    # Fork the second time to make sure the process is not a session leader.
    #   This apparently prevents us from taking control of a TTY.
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        logger.critical('Failed to give up session leadership: %d (%s)' %
                        (e.errno, e.strerror))
        sys.exit(1)

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, sys.stdin.fileno())
    os.dup2(devnull, sys.stdout.fileno())
    os.dup2(devnull, sys.stderr.fileno())
    os.close(devnull)

    pid = str(os.getpid())
    pidFile = file(PID_FILE, 'w')
    pidFile.write('%s\n' % pid)
    pidFile.close()

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
config['network_activation_timeout'] = config_helper.verify_number_exists(config_file, 'network_activation_timeout')
config['sleep_range'] = config_helper.verify_number_exists(config_file, 'sleep_range')

config['wired_network_name'] = config_helper.verify_string_exists(
    config_file, 'wired_network_name')
config['wifi_network_names'] = config_helper.verify_string_exists(
    config_file, 'wifi_network_names').split(',')
config['nameservers'] = config_helper.verify_string_exists(
    config_file, 'nameservers').split(',')
config['dns_queries'] = config_helper.verify_string_exists(
    config_file, 'dns_queries').split(',')

config['backup_network_name'] = config_helper.verify_string_exists(
    config_file, 'backup_network_name')
config['backup_network_max_usage_delay'] = config_helper.verify_number_exists(
    config_file, 'backup_network_max_usage_delay')
config['backup_network_failed_max_usage_delay'] = config_helper.verify_number_exists(
    config_file, 'backup_network_failed_max_usage_delay')

daemonize()


def sig_term_handler(signal, stack_frame):
    """Quit when SIGTERM is received."""
    logger.info('Received SIGTERM, quitting.')
    sys.exit(0)

signal.signal(signal.SIGTERM, sig_term_handler)

try:
    the_checker = netcheck.NetCheck(config)
    the_checker.check_loop()

except Exception as e:
    logger.critical('%s: %s\n' % (type(e).__name__, e.message))
    logger.error(traceback.format_exc())
    sys.exit(1)
