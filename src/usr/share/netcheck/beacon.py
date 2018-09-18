""" NetCheck beacon
beacon.py provides the Beacon class for easy determination of network availability. It
implements rate limiting and directory checking.
"""

import os
import time
import netcheckbeacon

BEACON_PATH = netcheckbeacon.BEACON_PATH
CHECK_INTERVAL = 5

class Beacon:
    """ Abstracts away the details of NetCheck's connection beacon."""
    def __init__(self):
        self.last_beacon_time = None
        self.next_check_time = time.time()

    def check(self):
        """ Check if a new beacon has been broadcast."""
        beacon_updated = False

        if time.time() > self.next_check_time:
            latest_beacon_time = self._read_beacon_time()

            if latest_beacon_time >= self.last_beacon_time:
                self.last_beacon_time = latest_beacon_time

                self.next_check_time = self.next_check_time + CHECK_INTERVAL
        return beacon_updated

    def _read_beacon_time(self):
        """ Retrieve the most recent time on which a beacon has been written."""
        beacon_time = None
        # TODO: Stuff all this in a try block.
        if os.path.isdir(BEACON_PATH):
            if netcheckbeacon.check_beacon_path_mount():
                file_list = os.listdir(BEACON_PATH)
                latest_file_name = sorted(file_list)[0]
                beacon_time = latest_file_name.split('---')[0]

        return beacon_time
