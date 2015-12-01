import os
import subprocess

# NetworkMetaManager provides an easy to work with interface for some of
# NetworkManager's basic functions.  It uses nmcli and handles both the current
# 1.x and the older 0.x output.

class NetworkMetaManager:

    def __init__(self, nmcli_timeout):

        # Set timeouts
        self.nmcli_timeout = nmcli_timeout

        # Get NetworkManager major version and dump it to self.major_version.
        #   nmcli parameters changed between 0.x and 1.x.
        raw_version = subprocess.check_output([ 'nmcli', '--version' ])
        version_string = raw_version.split()[3]
        self.major_version = int(version_string.split('.')[0])

        # Easy /dev/null access
        self.devnull = open(os.devnull, 'w')
 
    # TODO: Method documentation
    # Return True upon success, False otherwise.
    #   Param command_list is a command split into a list, not a list of separate commands.
    def _subprocess_call(self, command_list):

        exit_code = None
        try:
            # Run command with subprocess.call, redirecting output to /dev/null.
            exit_code = subprocess.call(command_list, stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)
        except:
            # Eat exceptions because it will properly return False this way.
            pass

        return exit_code == 0

    # Try to connect to a network, return true on success, false on failure
    def connect(self, network_name):

        # Different versions have different parameters
        if (self.major_version < 1):
            nmcli_command = ['nmcli', 'connection', 'up', 'id', network_name, '--timeout', '%d' % self.nmcli_timeout]

        elif (self.major_version >= 1):
            nmcli_command = ['nmcli', '-w', '%d' % self.nmcli_timeout, 'connection', 'up', network_name]

        return self._subprocess_call(nmcli_command)

    # Try to disconnect a network.
    def disconnect(self, network_name):

        if (self.major_version < 1):
            # disconnecting does not accept a timeout option, apparently.
            nmcli_command = ['nmcli', 'connection', 'down', 'id', network_name]
        elif (self.major_version >= 1):
            nmcli_command = ['nmcli', '-w', '%d' % self.nmcli_timeout, 'connection', 'down', network_name]

        return self._subprocess_call(nmcli_command)

    # Check for network connectivity, not including DNS
    def is_connected(self, network_name):

        nmcli_command = ['nmcli', 'c', 's']
        if (network_name in subprocess.check_output(nmcli_command)):
            return True
        else:
            return False

    # Get the current IP address for network_name's interface
    def get_interface_ip(self, network_name):

        interface_ip = None
        # yucky text parsing
        if (self.major_version < 1):
            # We are only interested in the first line of this output.
            # It should look something like this:
            # IP4.ADDRESS[1]:ip = 255.255.255.255/255, gw = 255.255.255.255
            nmcli_command = ['nmcli', '-t', '-f', 'ip', 'connection', 'status', 'id', network_name]
            ip_line = subprocess.check_output(nmcli_command).split('\n')[0]
            ip_raw = ip_line.split()[2]
            interface_ip = ip_raw.split('/')[0]

        elif (self.major_version >= 1):
            # I can't test this on this system.  It should work though.
            # TODO: Test this if we care enough to.
            nmcli_command = ['nmcli', '-t', '-f', 'ip4.address', 'connection', 'show', network_name]
            ip_raw = subprocess.check_output(nmcli_command).split(':')[1]
            return ip_raw.split('/')[0]

        return interface_ip
 

    # Get the current gateway address for network_name
    def get_gateway_ip(self, network_name):

        gateway_ip = None
        # more yucky text parsing
        if (self.major_version < 1):
            nmcli_command = ['nmcli', '-t', '-f', 'ip', 'connection', 'status', 'id', network_name]
            # We are only interested in the first line of this output.
            # It should look something like this:
            # IP4.ADDRESS[1]:ip = 255.255.255.255/255, gw = 255.255.255.255
            ip_line = subprocess.check_output(nmcli_command).split('\n')[0]
            gateway_ip = ip_line.split()[5]

        elif (self.major_version >= 1):
            # I can't test this on this system either.
            # TODO: Test this if we care enough to.
            nmcli_command = ['nmcli', '-t', '-f', 'ip4.gateway', 'connection', 'show', network_name]
            ip_raw = subprocess.check_output(nmcli_command).split(':')[1]
            gateway_ip = ip_raw.replace('\n', '')

        return gateway_ip

