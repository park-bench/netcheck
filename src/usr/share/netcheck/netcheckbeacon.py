# The purpose of this module is to provide a mechanism for NetCheck to broadcast a signal
#   when it connects to a new network.

import datetime
import os
import stat
import subprocess

BEACON_PATH = "/run/netcheck/"

def init(uid, gid):
    """ Initial configuration of the beacon directory. """
    # Create BEACON_PATH if it's not there.
    if not os.path.isdir(BEACON_PATH):
        # create path
        pass

    # Create ramdisk if it isn't already mounted as one.
    if not check_beacon_path_mount():
        # mount ramdisk
        pass
    
    # Sometime in the near future, this will not run as root.
    os.chown(BEACON_PATH, uid, gid)
    # Set permissions to xrwxr------
    mode = stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXGRP | stat.S_IRGRP
    os.chmod(BEACON_PATH, mode)

def send():
    """ Place a new file in the beacon directory. """
    # Assemble a filename: <datetime---random number>
    # Write file to a partial directory
    # Move file to beacon directory
    pass

def check_beacon_path_mount():
    """ Checks that the beacon path is a directory and is mounted as a ramdisk."""
    return 'none on {0} type tmpfs'.format(BEACON_PATH) in str(subprocess.check_output('mount'))
