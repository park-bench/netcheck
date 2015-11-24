import os
import subprocess

class NetworkMetaManager:
    def __init__(self, nmcli_timeout, dig_timeout):
        # Get NetworkManager major version and dump it to self.major_version
        # nmcli parameters changed between 0.x and 1.x
        raw_version = subprocess.check_output([ 'nmcli', '--version' ])
        version_string = raw_version.split()[3]
        self.major_version = int(version_string.split('.')[0])

        # Set timeouts
        self.nmcli_timeout = nmcli_timeout
        self.dig_timeout = dig_timeout
        
    def _subprocess_call(self, command_list):
        # Run command with subprocess.call, redirecting output to /dev/null.
        # Return True upon success, False otherwise.
        # command_list is a command split into a list, not a list of separate commands.
        exit_code = None
        try:
            devnull = open(os.devnull, 'w')
            exit_code = subprocess.call(command_list, stdin=devnull, stdout=devnull, stderr=devnull)
            devnull.close()
        except:
            # Eat exceptions because it will properly return False this way.
            pass

        if(exit_code == 0):
            return True
        else:
            return False

    def connect(self, network_name):
        # Try to connect to a network, return true on success, false on failure
        # Different versions have different parameters
        if(self.major_version == 0):
            nmcli_command = ['nmcli', 'connection', 'up', 'id', network_name, '--timeout', str(self.nmcli_timeout)]

        elif(self.major_version >= 1):
            nmcli_command = ['nmcli', '-w', str(self.nmcli_timeout), 'connection', 'up', network_name]

        return self._subprocess_call(nmcli_command)

    def disconnect(self, network_name):
        # Try to disconnect a network.
        if(self.major_version == 0):
            # disconnecting does not accept a timeout option, apparently.
            nmcli_command = ['nmcli', 'connection', 'down', 'id', network_name]
        elif(self.major_version >= 1):
            nmcli_command = ['nmcli', '-w', str(self.nmcli_timeout), 'connection', 'down', network_name]

        return self._subprocess_call(nmcli_command)

    def is_connected(self, network_name):
        # Check for network connectivity, not including DNS
        nmcli_command = ['nmcli', 'c', 's']
        if(network_name in subprocess.check_output(nmcli_command)):
            return True
        else:
            return False

    def get_interface_ip(self, network_name):
        # Get the current IP address for network_name's interface
        if(self.is_connected(network_name)):
            # yucky text parsing
            if(self.major_version == 0):
                nmcli_command = ['nmcli', '-t', '-f', 'ip', 'connection', 'status', 'id', network_name]
                ip_line = subprocess.check_output(nmcli_command).split('\n')[0]
                ip_raw = ip_line.split()[2]
                return ip_raw.split('/')[0]

            elif(self.major_version >= 1):
                # I can't test this on this system.  It should work though.
                # TODO: Test this if we care enough to.
                nmcli_command = ['nmcli', '-t', '-f', 'ip4.address', 'connection', 'show', network_name]
                ip_raw = subprocess.check_output(nmcli_command).split(':')[1]
                return ip_raw.split('/')[0]
        else:
            # TODO: Handle this case, throw in a log message.
            pass
            

    def get_gateway_ip(self, network_name):
        # Get the current gateway address for network_name
        if(self.is_connected(network_name)):
            # more yucky text parsing
            if(self.major_version == 0):
                nmcli_command = ['nmcli', '-t', '-f', 'ip', 'connection', 'status', 'id', network_name]
                ip_line = subprocess.check_output(nmcli_command).split('\n')[0]
                return ip_line.split()[5]

            elif(self.major_version >= 1):
                # I can't test this on this system either.
                # TODO: Test this if we care enough to.
                nmcli_command = ['nmcli', '-t', '-f', 'ip4.gateway', 'connection', 'show', network_name]
                ip_raw = subprocess.check_output(nmcli_command).split(':')[1]
                return ip_raw.replace('\n', '')
        else:
            # TODO: Handle this case, throw in a log message.
            pass

