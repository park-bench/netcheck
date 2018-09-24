# The purpose of this module is to provide a mechanism for NetCheck to broadcast a signal
#   when it connects to a new network.

import datetime
import logging
import os
import stat
import subprocess

BEACON_PATH = "/var/spool/netcheck/beacon/"

class BeaconBroadcaster(object):
    """ Provides a mechanism for NetCheck to tell other daemons that it has connected to a
    network.
    """

    def __init__(self, uid, gid):
        """ Initial configuration of the beacon directory.

        uid: The UID that NetCheck runs under
        gid: The GID that NetCheck runs under
        """

        self.logger = logging.getLogger(__name__)

        if not os.path.isdir(BEACON_PATH):
            try:
                mode = stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXGRP | stat.S_IRGRP
                # The mode argument is not used here because the documentation is unclear about
                #   when it will not work.
                os.makedirs(BEACON_PATH)

            except Exception as exception:
                # print a log message and raise an init exception
                pass


        try:
            # Sometime in the near future, this will not run as root.
            os.chown(BEACON_PATH, uid, gid)
            # Set permissions to xrwxr------
            os.chmod(BEACON_PATH, mode)

        except Exception as exception:
            # print a log message and raise an init exception
            pass

        if not self.check_beacon_path_mount():
            # TODO: Consider using subprocess.check_call instead. It raises exceptions.
            subprocess.call(['mount', '-t', 'tmpfs', '-o', '-size=25%', 'none', BEACON_PATH])

    def send(self):
        """ Place a new file in the beacon directory. """
        # Assemble a filename: <datetime---random number>
        # Write file to a partial directory
        # Move file to beacon directory
        pass

    def check_beacon_path_mount(self):
        """ Checks that the beacon path is a directory and is mounted as a ramdisk."""
        return 'none on {0} type tmpfs'.format(BEACON_PATH) in str(subprocess.check_output('mount'))
