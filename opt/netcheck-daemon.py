#!/usr/bin/env python2

import checkers
import os
import signal
import sys
import timber
import traceback

LOG_FILE = '/var/opt/log/checkers.log'
PID_FILE = '/var/opt/run/checkers.pid'
LOG_LEVEL = 'trace'

logger = timber.get_instance_with_filename(LOG_FILE, LOG_LEVEL)

def daemonize():
    # Fork the first time to make init our parent.
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError, e:
        logger.fatal("Failed to make parent process init: %d (%s)" % (e.errno, e.strerror))
        sys.exit(1)
  
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
    logger.fatal("Recieved SIGTERM, quitting.")
    sys.exit(0)

signal.signal(signal.SIGTERM, sig_term_handler)

try:
    wired_network_name = 'The Wired'
    wifi_network_names = [ 'xfinitywifi', 'CivicLab' ]
    nameservers = [ '8.8.8.8', '31.220.5.106', '213.73.91.35' ]
    queries = [ 'google.com', 'facebook.com', 'wikipedia.org']
    the_checker = checkers.checker(wired_network_name, wifi_network_names, nameservers, queries)
    the_checker.check_loop()

except Exception as e:
    logger.fatal("%s: %s\n" % (type(e).__name__, e.message))
    logger.fatal(traceback.format_exc())
    sys.exit(1)
