#!/usr/bin/python3

# Copyright 2015-2020 Joel Allen Luellwitz and Emily Frost
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

# TODO: Eventually consider running in a chroot or jail. (gpgmailer issue 17)

__author__ = 'Joel Luellwitz and Emily Frost'
__version__ = '0.8'

import grp
import logging
import os
import pwd
import signal
import stat
import sys
import traceback
import configparser
import daemon
from lockfile import pidlockfile
import prctl
from parkbenchcommon import broadcaster
from parkbenchcommon import confighelper
import _prctl  # Necesary to address https://github.com/seveas/python-prctl/issues/21
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
PROCESS_GROUP_NAME = PROGRAM_NAME
PROGRAM_UMASK = 0o027  # -rw-r----- and drwxr-x---


class InitializationException(Exception):
    """Indicates an expected fatal error occurred during program initialization.
    Initialization is implied to mean, before daemonization.
    """


def get_user_and_group_ids():
    """Get user and group information for dropping privileges.

    Returns the user and group IDs that the program should eventually run as.
    """
    try:
        program_user = pwd.getpwnam(PROCESS_USERNAME)
    except KeyError as key_error:
        message = 'User %s does not exist.' % PROCESS_USERNAME
        raise InitializationException(message) from key_error
    try:
        program_group = grp.getgrnam(PROCESS_GROUP_NAME)
    except KeyError as key_error:
        message = 'Group %s does not exist.' % PROCESS_GROUP_NAME
        raise InitializationException(message) from key_error

    return program_user.pw_uid, program_group.gr_gid


def read_configuration_and_create_logger(program_uid, program_gid):
    """Reads the configuration file and creates the application logger. This is done in the
    same function because part of the logger creation is dependent upon reading the
    configuration file.

    program_uid: The system user ID this program should drop to before daemonization.
    program_gid: The system group ID this program should drop to before daemonization.
    Returns the read system config, a confighelper instance, and a logger instance.
    """
    print('Reading %s...' % CONFIGURATION_PATHNAME)

    if not os.path.isfile(CONFIGURATION_PATHNAME):
        raise InitializationException(
            'Configuration file %s does not exist. Quitting.' % CONFIGURATION_PATHNAME)

    config_file = configparser.SafeConfigParser()
    config_file.read(CONFIGURATION_PATHNAME)

    config = {}
    config_helper = confighelper.ConfigHelper()
    # Figure out the logging options so that can start before anything else.
    # TODO: Eventually add a verify_string_in_list method. (gpgmailer issue 20)
    config['log_level'] = config_helper.verify_string_exists(config_file, 'log_level')

    # Create logging directory.  drwxr-x--- netcheck netcheck
    log_mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP
    # TODO: Look into defaulting the logging to the console until the program gets more
    #   bootstrapped. (gpgmailer issue 18)
    print('Creating logging directory %s.' % LOG_DIR)
    if not os.path.isdir(LOG_DIR):
        # Will throw exception if directory cannot be created.
        os.makedirs(LOG_DIR, log_mode)
    os.chown(LOG_DIR, program_uid, program_gid)
    os.chmod(LOG_DIR, log_mode)

    # Temporarily drop permissions and create the handle to the logger.
    print('Configuring logger.')
    os.setegid(program_gid)
    os.seteuid(program_uid)
    config_helper.configure_logger(os.path.join(LOG_DIR, LOG_FILE), config['log_level'])

    logger = logging.getLogger(__name__)

    logger.info('Verifying non-logging configuration.')

    config['run_as_root'] = config_helper.verify_boolean_exists(config_file, 'run_as_root')

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

    config['dns_timeout'] = config_helper.verify_number_within_range(
        config_file, 'dns_timeout', lower_bound=0)
    config['connection_activation_timeout'] = config_helper.verify_number_within_range(
        config_file, 'connection_activation_timeout', lower_bound=0)
    config['connection_periodic_check_time'] = config_helper.verify_number_within_range(
        config_file, 'connection_periodic_check_time', lower_bound=0)
    config['available_connections_check_delay'] = config_helper.verify_number_within_range(
        config_file, 'available_connections_check_delay', lower_bound=26)

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

    return config, config_helper, logger


# TODO: Consider checking ACLs. (gpgmailer issue 22)
def verify_safe_file_permissions():
    """Crashes the application if unsafe file permissions exist on application configuration
    files.
    """
    # The configuration file should be owned by root.
    config_file_stat = os.stat(CONFIGURATION_PATHNAME)
    if config_file_stat.st_uid != 0:
        raise InitializationException(
            'File %s must be owned by root.' % CONFIGURATION_PATHNAME)
    if bool(config_file_stat.st_mode & (stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH)):
        raise InitializationException(
            "File %s cannot have 'other user' access permissions set."
            % CONFIGURATION_PATHNAME)


def warn_about_suspect_network_manager_configuration(config):
    """Logs a warning if it is detected that the user did not follow the README instructions
    and is subverting some of the system's security measures. This method assumes the
    program is currently running with full root privileges.

    The checks in this method are not perfect but should, in practice, work nearly 100% of
    the time.

    config: The program configuration dictionary. Used to determine if the program is running
      as root.
    """

    # See if NetworkManager polkit authentication is enabled.
    polkit_auth_enabled = True
    network_manager_config_pathname = '/etc/NetworkManager/NetworkManager.conf'
    try:
        with open(network_manager_config_pathname, 'r') as network_manager_config:
            for line in network_manager_config:
                lowercase_line = line.lower()
                if 'auth-polkit' in lowercase_line and 'false' in lowercase_line:
                    polkit_auth_enabled = False
    except Exception as exception:  #pylint: disable=broad-except
        logger.warning('Cannot access %s. %s: %s', network_manager_config_pathname,
                       str(exception), traceback.format_exc())
        # Yes, we are eating this exception. This is a non-fatal error.

    # See if any user can communicate with NetworkManager via DBus.
    any_user_dbus_config = False
    network_manager_dbus_config_pathname = \
        '/etc/dbus-1/system.d/org.freedesktop.NetworkManager.conf'
    try:
        with open(network_manager_dbus_config_pathname, 'r') as network_manager_dbus_config:
            for line in network_manager_dbus_config:
                if '<policy context="default">' in line.lower():
                    any_user_dbus_config = True
    except Exception as exception:  #pylint: disable=broad-except
        logger.warning('Cannot access %s. %s: %s', network_manager_dbus_config_pathname,
                       str(exception), traceback.format_exc())
        # Yes, we are eating this exception. This is a non-fatal error.

    if not polkit_auth_enabled:
        if config['run_as_root']:
            logger.warning(
                'NetworkManager polkit authentication appears to be disabled. '
                'NetworkManager polkit authentication should probably be enabled when this '
                'daemon is run as the root user.')
        else:
            if any_user_dbus_config:
                logger.warning(
                    "NetworkManager polkit authentication appears to be disabled and "
                    "NetworkManager's DBus configuration appears to allow communication "
                    "from any user. This is a potential security risk! Refer to the program "
                    "README.md for instuctions about how to correct this.")


def create_directory(system_path, program_dirs, uid, gid, mode):
    """Creates directories if they do not exist and sets the specified ownership and
    permissions.

    system_path: The system path that the directories should be created under. These are
      assumed to already exist. The ownership and permissions on these directories are not
      modified.
    program_dirs: A string representing additional directories that should be created under
      the system path that should take on the following ownership and permissions.
    uid: The system user ID that should own the directory.
    gid: The system group ID that should be associated with the directory.
    mode: The unix standard 'mode bits' that should be associated with the directory.
    """
    logger.info('Creating directory %s.', os.path.join(system_path, program_dirs))

    path = system_path
    for directory in program_dirs.strip('/').split('/'):
        path = os.path.join(path, directory)
        if not os.path.isdir(path):
            # Will throw exception if directory cannot be created.
            os.makedirs(path, mode)
        os.chown(path, uid, gid)
        os.chmod(path, mode)


def drop_permissions_forever(config, uid, gid):
    """Drops escalated permissions forever to the specified user and group.

    config: The program configuration dictionary used to determine if the program is running
      as root.
    uid: The system user ID to drop to if the program is not running as root.
    gid: The system group ID to drop to if the program is not running as root.
    """
    if config['run_as_root']:
        logger.info('Dropping capabilities for root user.')
    else:
        logger.info('Dropping permissions for user %s.', PROCESS_USERNAME)
        prctl.securebits.no_setuid_fixup = True
        os.initgroups(PROCESS_USERNAME, gid)
        os.setgid(gid)
        os.setuid(uid)

    # Conditionally remove all capabilities from 0 to 200 because prctl.limit doesn't know
    #   about newer capabilities. (200 is an abitrary limit but right now there are only
    #   about 40 capabilities.)
    for capability_index in range(0, 200):
        #pylint: disable=no-member
        if capability_index != prctl.CAP_NET_RAW \
                and capability_index != prctl.CAP_SETPCAP:
            # Conditionally keep CAP_SETUID and CAP_SETGID for switching the owner and group
            #   when daemonizing.
            if not config['run_as_root'] and (capability_index == prctl.CAP_SETUID
                                              or capability_index == prctl.CAP_SETGID):
                #pylint: enable=no-member
                remove_effective = [capability_index]
                remove_permitted = [capability_index]
                remove_inheritable = []
            else:
                remove_effective = [capability_index]
                remove_permitted = [capability_index]
                remove_inheritable = [capability_index]

            # Referencing internal _prctl to address
            #   https://github.com/seveas/python-prctl/issues/21 .
            _prctl.set_caps(
                [], [], [], remove_effective, remove_permitted, remove_inheritable)

    # Remove all capabilities except CAP_NET_RAW and CAP_SETUID and CAP_SETGID from the
    #   inheritable set. This includes removing any capabilities the above may have
    #   missed (including prctl.SETPCAP). CAP_SETUID and CAP_SETGID might have already been
    #   removed from the inheritable set above.
    #pylint: disable=no-member
    prctl.cap_effective.limit(prctl.CAP_NET_RAW)
    prctl.cap_inheritable.limit(prctl.CAP_NET_RAW, prctl.CAP_SETUID, prctl.CAP_SETGID)
    prctl.cap_permitted.limit(prctl.CAP_NET_RAW)
    #pylint: enable=no-member


def sig_term_handler(signal, stack_frame):  #pylint: disable=unused-argument
    """Signal handler for SIGTERM. Quits when SIGTERM is received.

    signal: Object representing the signal thrown.
    stack_frame: Represents the stack frame.
    """
    logger.info('SIGTERM received. Quitting.')
    sys.exit(0)


def setup_daemon_context(config, log_file_handle, program_uid, program_gid):
    """Creates the daemon context. Specifies daemon permissions, PID file information, and
    the signal handler.

    config: The program configuration dictionary used to determine if the program is running
      as root.
    log_file_handle: The file handle to the log file.
    program_uid: The system user ID that should own the daemon process if the program is
      not running as root.
    program_gid: The system group ID that should be assigned to the daemon process if the
      program is not running as root.
    Returns the daemon context.
    """
    daemon_context = daemon.DaemonContext(
        working_directory='/',
        pidfile=pidlockfile.PIDLockFile(
            os.path.join(SYSTEM_PID_DIR, PROGRAM_PID_DIRS, PID_FILE)),
        umask=PROGRAM_UMASK,
    )

    daemon_context.signal_map = {
        signal.SIGTERM: sig_term_handler,
    }

    daemon_context.files_preserve = [log_file_handle]

    # Set the UID and GID to 'netcheck' user and group.
    if not config['run_as_root']:
        daemon_context.uid = program_uid
        daemon_context.gid = program_gid

    return daemon_context


os.umask(PROGRAM_UMASK)
program_uid, program_gid = get_user_and_group_ids()
config, config_helper, logger = read_configuration_and_create_logger(
    program_uid, program_gid)

try:
    verify_safe_file_permissions()

    # Re-establish root permissions to create required directories.
    os.seteuid(os.getuid())
    os.setegid(os.getgid())

    warn_about_suspect_network_manager_configuration(config)

    if config['run_as_root']:
        # Only the log file needs to be created with non-root ownership.
        program_uid = os.getuid()
        program_uid = os.getgid()

    # Non-root users cannot create files in /run, so create a directory that can be written
    #   to. Full access to user only.
    #   drwx------ netcheck netcheck  or  drwx------ root root
    create_directory(SYSTEM_PID_DIR, PROGRAM_PID_DIRS, program_uid, program_gid,
                     stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    broadcaster = broadcaster.Broadcaster(
        program_name='netcheck', broadcast_name='gateway-changed', uid=program_uid,
        gid=program_gid)

    # Configuration has been read and directories setup. Now drop permissions forever.
    drop_permissions_forever(config, program_uid, program_gid)

    daemon_context = setup_daemon_context(
        config, config_helper.get_log_file_handle(), program_uid, program_gid)

    logger.info('Daemonizing...')
    with daemon_context:
        logger.info('Initializing NetCheck.')
        the_checker = netcheck.NetCheck(config, broadcaster)
        the_checker.start()

except Exception as exception:
    logger.critical('Fatal %s: %s\n%s', type(exception).__name__, str(exception),
                    traceback.format_exc())
    raise exception
