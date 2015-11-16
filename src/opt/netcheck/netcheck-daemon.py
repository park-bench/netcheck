#!/usr/bin/env python2

import confighelper
import ConfigParser
import netcheck
import os
import signal
import sys
import timber
import traceback

# TODO: Follow Python variable conventions (lowercase)
PID_FILE = '/var/opt/run/netcheck.pid'

# TODO: Break out into common library.
def daemonize():
    # Fork the first time to make init our parent.
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError, e:
        logger.fatal("Failed to make parent process init: %d (%s)" % (e.errno, e.strerror))
        sys.exit(1)
 
    # TODO: Consider locking this down. 
    os.chdir("/")  # Change the working directory
    os.setsid()  # Create a new process session.
    os.umask(0)

    # Fork the second time to make sure the process is not a session leader. 
    #   This apparently prevents us from taking control of a TTY.
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError, e:
        logger.fatal("Failed to give up session leadership: %d (%s)" % (e.errno, e.strerror))
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
    pidFile = file(PID_FILE,'w')
    pidFile.write("%s\n" % pid)
    pidFile.close()

# Verify config file here.

config_file = ConfigParser.SafeConfigParser()
config_file.read('/etc/opt/netcheck/netcheck.conf')

# Get logging options first.
config_helper = confighelper.ConfigHelper()
log_file = config_helper.verify_string_exists_prelogging(config_file, 'log_file')
log_level = config_helper.verify_string_exists_prelogging(config_file, 'log_level')

# Start the logger.
logger = timber.get_instance_with_filename(log_file, log_level)

# Now read the rest of them.
config = {}
config['dig_timeout'] = config_helper.verify_number_exists(config_file, 'dig_timeout')
config['nmcli_timeout'] = config_helper.verify_number_exists(config_file, 'nmcli_timeout')

config['wired_network_name'] = config_helper.verify_string_exists(config_file, 'wired_network_name')
config['wifi_network_names'] = config_helper.verify_string_exists(config_file, 'wifi_network_names').split(',')
config['nameservers'] = config_helper.verify_string_exists(config_file, 'nameservers').split(',')
config['dns_queries'] = config_helper.verify_string_exists(config_file, 'dns_queries').split(',')

daemonize()

# Quit when SIGTERM is received
def sig_term_handler(signal, stack_frame):
    logger.info("Recieved SIGTERM, quitting.")
    sys.exit(0)

signal.signal(signal.SIGTERM, sig_term_handler)

try:
    the_checker = netcheck.checker(config)
    the_checker.check_loop()

except Exception as e:
    logger.fatal("%s: %s\n" % (type(e).__name__, e.message))
    logger.error(traceback.format_exc())
    sys.exit(1)
