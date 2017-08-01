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

# Monitors Internet availability and switches to alternate networks in a
#   predefined order if needed.

# TODO: Consider running in a chroot or jail.
# TODO: Add support for verifying all networks exist before daemonize.

import confighelper
import ConfigParser
import daemon
import grp
import logging
import netcheck
import os
# TODO: Remove try/except when we drop support for Ubuntu 14.04 LTS.
try:
    from lockfile import pidlockfile
except ImportError:
    from daemon import pidlockfile
import pwd
import signal
import stat
import sys
import traceback

# Constants
program_name = 'netcheck'
pid_file = '/run/netcheck.pid'
configuration_pathname = os.path.join('/etc', program_name, '%s.conf' % program_name)
system_pid_dir = '/run'
program_pid_dirs = program_name
pid_file = '%s.pid' % program_name
log_dir = os.path.join('/var/log', program_name)
log_file = '%s.log' % program_name
process_username = program_name
process_group_name = program_name


# Get user and group information for dropping privileges.
#
# Returns the user and group IDs that the program should eventually run as.
def get_user_and_group_ids():
    try:
        program_user = pwd.getpwnam(process_username)
    except KeyError as key_error:
        raise Exception('User %s does not exist.' % process_username, key_error)
    try:
        program_group = grp.getgrnam(process_group_name)
    except KeyError as key_error:
        raise Exception('Group %s does not exist.' % process_group_name, key_error)

    return (program_user.pw_uid, program_group.gr_gid)


# Reads the configuration file and creates the application logger. This is done in the
#   same function because part of the logger creation is dependent upon reading the
#   configuration file.
#
# program_uid: The system user ID this program should drop to before daemonization.
# program_gid: The system group ID this program should drop to before daemonization.
# Returns the read system config, a confighelper instance, and a logger instance.
def read_configuration_and_create_logger(program_uid, program_gid):
    config_parser = ConfigParser.SafeConfigParser()
    config_parser.read(configuration_pathname)

    # Logging config goes first
    config = {}
    config_helper = confighelper.ConfigHelper()
    config['log_level'] = config_helper.verify_string_exists_prelogging(config_parser, 'log_level')

    # Create logging directory.
    log_mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
    # TODO: Look into defaulting the logging to the console until the program gets more bootstrapped.
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

    logger = logging.getLogger('%s-daemon' % program_name)

    logger.info('Verifying non-logging config')

    config['dig_timeout'] = config_helper.verify_number_exists(config_parser, 'dig_timeout')
    config['nmcli_timeout'] = config_helper.verify_number_exists(config_parser, 'nmcli_timeout')
    config['sleep_range'] = config_helper.verify_number_exists(config_parser, 'sleep_range')

    config['wired_network_name'] = \
        config_helper.verify_string_exists(config_parser, 'wired_network_name')
    config['wifi_network_names'] = \
        config_helper.verify_string_exists(config_parser, 'wifi_network_names').split(',')
    config['nameservers'] = \
        config_helper.verify_string_exists(config_parser, 'nameservers').split(',')
    config['dns_queries'] = \
        config_helper.verify_string_exists(config_parser, 'dns_queries').split(',')

    config['backup_network_name'] = \
        config_helper.verify_string_exists(config_parser, 'backup_network_name')
    config['backup_network_max_usage_delay'] = \
            config_helper.verify_number_exists(config_parser, 'backup_network_max_usage_delay')
    config['backup_network_failed_max_usage_delay'] = \
            config_helper.verify_number_exists(config_parser, 'backup_network_failed_max_usage_delay')

    return (config, config_helper, logger)


# Creates directories if they do not exist and sets the specified ownership and permissions.
#
# system_path: The system path that the directories should be created under. These are assumed to
#   already exist. The ownership and permissions on these directories are not modified.
# program_dirs: Additional directories that should be created under the system path that should take
#   on the following ownership and permissions.
# uid: The system user ID that should own the directory.
# gid: The system group ID that should own be associated with the directory.
# mode: The umask of the directory access permissions.
def create_directory(system_path, program_dirs, uid, gid, mode):

    logger.info('Creating directory %s.' % os.path.join(system_path, program_dirs))

    for directory in program_dirs.strip('/').split('/'):
        path = os.path.join(system_path, directory)
        if not os.path.isdir(path):
            # Will throw exception if file cannot be created.
            os.makedirs(path, mode)
        os.chown(path, uid, gid)
        os.chmod(path, mode)


# Drops escalated permissions forever to the specified user and group.
#
# uid: The system user ID to drop to.
# gid: The system group ID to drop to.
def drop_permissions_forever(uid, gid):
    logger.info('Dropping permissions for user %s.' % process_username)
    os.initgroups(process_username, gid)
    os.setgid(gid)
    os.setuid(uid)


# Creates the daemon context. Specifies daemon permissions, PID file information, and
#   signal handler.
#
# log_file_handle: The file handle to the log file.
# Returns the daemon context.
def setup_daemon_context(log_file_handle, program_uid, program_gid):

    daemon_context = daemon.DaemonContext(
        working_directory = '/',
        pidfile = pidlockfile.PIDLockFile(os.path.join(system_pid_dir, program_pid_dirs, pid_file)),
        umask = 0o117,  # Read/write by user and group.
        )

    daemon_context.signal_map = {
        signal.SIGTERM : sig_term_handler,
        }

    daemon_context.files_preserve = [log_file_handle]

    # Set the UID and PID to 'netcheck' user and group.
    daemon_context.uid = program_uid
    daemon_context.gid = program_gid

    return daemon_context


# Signal handler for SIGTERM. Quits when SIGTERM is received.
#
# signal: Object representing the signal thrown.
# stack_frame: Represents the stack frame.
def sig_term_handler(signal, stack_frame):
    logger.info("Received SIGTERM, quitting.")
    sys.exit(0)

program_uid, program_gid = get_user_and_group_ids()

config, config_helper, logger = read_configuration_and_create_logger(program_uid, program_gid)

try:
    # Non-root users cannot create files in /run, so create a directory that can be written to.
    #   Full access to user only.
    create_directory(system_pid_dir, program_pid_dirs, program_uid, program_gid,
        stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    # Configuration has been read and directories setup. Now drop permissions forever.
    drop_permissions_forever(program_uid, program_gid)

    daemon_context = setup_daemon_context(config_helper.get_log_file_handle(), program_uid, program_gid)

    net_check = netcheck.NetCheck(config)

    with daemon_context:
        try:
            net_check.check_loop()

        except Exception as exception:
            logger.critical('Fatal %s: %s\n' % (type(exception).__name__, exception.message))
            logger.critical(traceback.format_exc())
            sys.exit(1)

except Exception as exception:
    logger.critical('Fatal %s: %s\n' % (type(exception).__name__, exception.message))
    logger.critical(traceback.format_exc())
    sys.exit(1)
