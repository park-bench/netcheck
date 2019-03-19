#!/usr/bin/env python2

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

"""Daemon to find and maintain the best connection to the Internet."""

__author__ = 'Joel Luellwitz and Emily Frost'
__version__ = '0.8'

# TODO: Consider running in a chroot or jail.

import grp
import logging
import os
import pwd
import signal
import stat
import sys
import traceback
import ConfigParser
import daemon
from lockfile import pidlockfile
import confighelper
from confighelper import ValidationException
import netcheck

# Constants
PROGRAM_NAME = 'netcheck'
CONFIGURATION_PATHNAME = os.path.join('/etc', PROGRAM_NAME, '%s.conf' % PROGRAM_NAME)
SYSTEM_PID_DIR = '/run'
PROGRAM_PID_DIRS = PROGRAM_NAME
PID_FILE = '%s.pid' % PROGRAM_NAME
LOG_DIR = os.path.join('/var/log', PROGRAM_NAME)
LOG_FILE = '%s.log' % PROGRAM_NAME
PROCESS_USERNAME = PROGRAM_NAME
PRODESS_GROUP_NAME = PROGRAM_NAME


def get_user_and_group_ids():
    """Get user and group information for dropping privileges.

    Returns the user and group IDs that the program should eventually run as.
    """
    try:
        program_user = pwd.getpwnam(PROCESS_USERNAME)
    except KeyError as key_error:
        raise Exception('User %s does not exist.' % process_username, key_error)
    try:
        program_group = grp.getgrnam(PROCESS_GROUP_NAME)
    except KeyError as key_error:
        raise Exception('Group %s does not exist.' % process_group_name, key_error)

    return (program_user.pw_uid, program_group.gr_gid)


def read_configuration_and_create_logger(program_uid, program_gid):
    """Reads the configuration file and creates the application logger. This is done in the
    same function because part of the logger creation is dependent upon reading the
    configuration file.

    program_uid: The system user ID this program should drop to before daemonization.
    program_gid: The system group ID this program should drop to before daemonization.
    Returns the read system config, a confighelper instance, and a logger instance.
    """
    config_file = ConfigParser.SafeConfigParser()
    config_file.read(CONFIGURATION_PATHNAME)

    # Get logging options first.
    config = {}
    config_helper = confighelper.ConfigHelper()
    config['log_level'] = config_helper.verify_string_exists(config_file, 'log_level')

    # Create logging directory.
    log_mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP \
        | stat.S_IROTH | stat.S_IXOTH
    # TODO: Look into defaulting the logging to the console until the program gets more
    #   bootstrapped.
    print('Creating logging directory %s.' % log_dir)
    if not os.path.isdir(log_dir):
        # Will throw exception if file cannot be created.
        os.makedirs(log_dir, log_mode)
    os.chown(log_dir, program_uid, program_gid)
    os.chmod(log_dir, log_mode)

    # Temporarily drop permission and create the handle to the logger.
    os.setegid(program_gid)
    os.seteuid(program_uid)
    config_helper.configure_logger(os.path.join(log_dir, log_file), config['log_level'])
    os.seteuid(os.getuid())
    os.setegid(os.getgid())

    logger = logging.getLogger(__name__)

    logger.info('Verifying non-logging configuration.')

    config['connection_ids'] = config_helper.verify_string_list_exists(
        config_file, 'connection_ids')
    config['nameservers'] = config_helper.verify_string_list_exists(
        config_file, 'nameservers')
    if len(config['nameservers']) < 2:
        message = "At least two nameservers are required."
        logger.critical(message)
        raise ValidationException(message)
    config['dns_queries'] = config_helper.verify_string_list_exists(
        config_file, 'dns_queries')
    if len(config['dns_queries']) < 2:
        message = "At least two domain names are required."
        logger.critical(message)
        raise ValidationException(message)

    config['dns_timeout'] = config_helper.verify_number_within_range(
        config_file, 'dns_timeout', lower_bound=0)
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

    return (config, config_helper, logger)


def create_directory(system_path, program_dirs, uid, gid, mode):
    """Creates directories if they do not exist and sets the specified ownership and
    permissions.

    system_path: The system path that the directories should be created under. These are
      assumed to already exist. The ownership and permissions on these directories are not
      modified.
    program_dirs: Additional directories that should be created under the system path that
      should take on the following ownership and permissions.
    uid: The system user ID that should own the directory.
    gid: The system group ID that should own be associated with the directory.
    mode: The umask of the directory access permissions.
    """
    logger.info('Creating directory %s.' % os.path.join(system_path, program_dirs))

    for directory in program_dirs.strip('/').split('/'):
        path = os.path.join(system_path, directory)
        if not os.path.isdir(path):
            # Will throw exception if file cannot be created.
            os.makedirs(path, mode)
        os.chown(path, uid, gid)
        os.chmod(path, mode)


def drop_permissions_forever(uid, gid):
    """Drops escalated permissions forever to the specified user and group.

    uid: The system user ID to drop to.
    gid: The system group ID to drop to.
    """
    logger.info('Dropping permissions for user %s.' % process_username)
    os.initgroups(PROCESS_USERNAME, gid)
    os.setgid(gid)
    os.setuid(uid)


def setup_daemon_context(log_file_handle, program_uid, program_gid):
    """Creates the daemon context. Specifies daemon permissions, PID file information, and
    the signal handler.

    log_file_handle: The file handle to the log file.
    program_uid: The system user ID the daemon should run as.
    program_pid: The system group ID the daemon should run as.
    Returns the daemon context.
    """
    daemon_context = daemon.DaemonContext(
        working_directory='/',
        pidfile=pidlockfile.PIDLockFile(
            os.path.join(SYSTEM_PID_DIR, PROGRAM_PID_DIRS, PID_FILE)),
        umask=0o117,  # Read/write by user and group.
        )

    daemon_context.signal_map = {
        signal.SIGTERM: sig_term_handler,
        }

    daemon_context.files_preserve = [log_file_handle]

    # Set the UID and PID to 'netcheck' user and group.
    daemon_context.uid = program_uid
    daemon_context.gid = program_gid

    return daemon_context


def sig_term_handler(signal, stack_frame):
    """Signal handler for SIGTERM. Quits when SIGTERM is received.

    signal: Object representing the signal thrown.
    stack_frame: Represents the stack frame.
    """
    logger.info('Received SIGTERM, quitting.')
    sys.exit(0)

program_uid, program_gid = get_user_and_group_ids()

config, config_helper, logger = read_configuration_and_create_logger(
    program_uid, program_gid)

try:
    # Non-root users cannot create files in /run, so create a directory that can be written
    #   to. Full access to user only.
    create_directory(SYSTEM_PID_DIR, PROGRAM_PID_DIRS, program_uid, program_gid,
        stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    # Configuration has been read and directories setup. Now drop permissions forever.
    drop_permissions_forever(program_uid, program_gid)

    daemon_context = setup_daemon_context(
        config_helper.get_log_file_handle(), program_uid, program_gid)

    # TODO: We might have to move this within the daemon_context due to dbus stuff.
    logger.info('Initializing NetCheck.')
    netcheck = netcheck.NetCheck(config)

    logger.info('Daemonizing...')
    with daemon_context:
        netcheck.start()

except Exception as exception:
    logger.critical('Fatal %s: %s', type(exception).__name__, str(exception))
    logger.critical(traceback.format_exc())
    raise
