#!/usr/bin/env python2

import netcheck
import os
import signal
import sys
import timber
import traceback

# TODO: Follow Python variable conventions (lowercase)
# TODO: Add configuration file support.
LOG_FILE = '/var/opt/log/netcheck.log'
PID_FILE = '/var/opt/run/netcheck.pid'
LOG_LEVEL = 'info'

logger = timber.get_instance_with_filename(LOG_FILE, LOG_LEVEL)

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
    
daemonize()

# Quit when SIGTERM is received
def sig_term_handler(signal, stack_frame):
    logger.info("Recieved SIGTERM, quitting.")
    sys.exit(0)

signal.signal(signal.SIGTERM, sig_term_handler)

try:
    wired_network_name = 'The Wired'
    wifi_network_names = [ 'xfinitywifi', 'CivicLab', 'SPACE' ]
    nameservers = [ '8.8.8.8', '31.220.5.106', '213.73.91.35' ]  # TODO: Do we want to keep using Google? There are many that are not logged.
    queries = [ 'google.com', 'facebook.com', 'wikipedia.org']
    the_checker = netcheck.checker(wired_network_name, wifi_network_names, nameservers, queries)
    the_checker.check_loop()

except Exception as e:
    logger.fatal("%s: %s\n" % (type(e).__name__, e.message))
    logger.error(traceback.format_exc())
    sys.exit(1)
