import os
import subprocess
import timber

# NetworkMetaManager provides an easy to work with interface for some of
#   NetworkManager's basic functions. It uses the 'nmcli' command and supports NetworkManager
#   versions 0.x and 1.x.
# TODO: Use the network manager API instead.
class NetworkMetaManager:


    def __init__(self, nmcli_timeout):

        self.logger = timber.get_instance()

        # Set timeouts
        self.nmcli_timeout = nmcli_timeout

        # Get NetworkManager major version and dump it to self.major_version.
        #   nmcli parameters changed between 0.x and 1.x.
        # TODO: Does the program bail if this command fails?
        raw_version = subprocess.check_output([ 'nmcli', '--version' ])
        version_string = raw_version.split()[3]
        self.major_version = int(version_string.split('.')[0])

        # Easy and efficient /dev/null access
        self.devnull = open(os.devnull, 'w')

        self.logger.info('NetworkMetaManager started with NetworkManager major ' + \
                'version %s.' % self.major_version)

 
    # Invokes a program on the system.
    #   Param command_list is a command split into a list, not a list of separate commands.
    #   Returns True upon success, False otherwise.
    def _subprocess_call(self, command_list):

        exit_code = None
        
        self.logger.trace('_subprocess_call: Calling "%s".' % ' '.join(command_list))
        try:
            # Run command with subprocess.call, redirecting output to /dev/null.
            exit_code = subprocess.call(command_list, stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)
            self.logger.trace('_subprocess_call: Subprocess returned code %d.' % exit_code)
        except subprocess.CalledProcessError as process_error:
            # Eat exceptions because it will properly return False this way.
            self.logger.error('Subprocess call failed!')

        return exit_code == 0


    # Try to connect to a network. Returns True on success, False on failure.
    def connect(self, network_name):

        # Different versions have different parameters
        if self.major_version < 1:
            nmcli_command = ['nmcli', 'connection', 'up', 'id', network_name, '--timeout', '%d' % self.nmcli_timeout]
        else:
            nmcli_command = ['nmcli', '-w', '%d' % self.nmcli_timeout, 'connection', 'up', network_name]

        connect_success = self._subprocess_call(nmcli_command)

        if connect_success:
            self.logger.trace('connect: Connected to %s.' % network_name)

        else:
            self.logger.debug('connect: Could not connect to %s.' % network_name)

        return connect_success


    # Try to disconnect a network. Returns True on success, False on failure.
    def disconnect(self, network_name):

        if self.major_version < 1:
            # Disconnecting does not accept a timeout option, apparently.
            #   This is not a problem because none of our code uses this method anyway.
            nmcli_command = ['nmcli', 'connection', 'down', 'id', network_name]
        else:
            nmcli_command = ['nmcli', '-w', '%d' % self.nmcli_timeout, 'connection', 'down', network_name]

        disconnect_success = self._subprocess_call(nmcli_command)

        if disconnect_success:
            self.logger.trace('disconnect: Disconnected from %s.' % network_name)
        else:
            self.logger.debug('disconnect: Disconnecting from %s failed!' % network_name)

        return disconnect_success


    # Check for network connectivity, not including DNS. Returns True if connected, False otherwise.
    def is_connected(self, network_name):

        self.logger.trace('is_connected: Checking connectivity for %s.' % network_name)

        nmcli_command = ['nmcli', 'c', 's']

        # TODO: Does this work right if the network name you are searching for is
        #   a subset of another network name?
        is_connected = network_name in subprocess.check_output(nmcli_command)

        if is_connected:
            self.logger.trace('is_connected: Connected to %s.' % network_name)
        else:
            self.logger.trace('is_connected: Not connected to %s.' % network_name)

        return is_connected


    # Get the current IP address for network_name's interface.
    # TODO: If the output of nmcli is not as expected, this method could throw an unexpected exception.
    # TODO: Compare IP address to regex to make sure it at least looks like an IP. While I don't think this is exploitable
    #   right now, we should still check the output for better security. Explicitly throw an exception if the output is
    #   not as expected.
    def get_interface_ip(self, network_name):

        self.logger.trace('get_interface_ip: Getting interface IP for %s.' % network_name)

        interface_ip = None
        # yucky text parsing
        if self.major_version < 1:
            # We are only interested in the first line of this output.
            #   It should look something like this:
            #   IP4.ADDRESS[1]:ip = 255.255.255.255/255, gw = 255.255.255.255
            nmcli_command = ['nmcli', '-t', '-f', 'ip', 'connection', 'status', 'id', network_name]
            ip_line = subprocess.check_output(nmcli_command).split('\n')[0]
            ip_raw = ip_line.split()[2]
            interface_ip = ip_raw.split('/')[0]

        else:
            # TODO: Test this if we care enough to. I can't test this on this system. It should work though.
            nmcli_command = ['nmcli', '-t', '-f', 'ip4.address', 'connection', 'show', network_name]
            ip_raw = subprocess.check_output(nmcli_command).split(':')[1]
            interface_ip = ip_raw.split('/')[0]

        self.logger.trace('get_interface_ip: Interface IP for %s is %s.' % (network_name, interface_ip))

        return interface_ip
 

    # Get the current gateway address for network_name.
    # TODO: If the output of nmcli is not as expected, this method could throw an unexpected exception.
    # TODO: Compare IP address to regex to make sure it at least looks like an IP. While I don't think this is exploitable
    #   right now, we should still check the output for better security. Explicitly throw an exception if the output is
    #   not as expected.
    def get_gateway_ip(self, network_name):

        self.logger.trace('get_gateway_ip: Getting gateway IP for %s.' % network_name)

        gateway_ip = None
        # More yucky text parsing
        if self.major_version < 1:
            nmcli_command = ['nmcli', '-t', '-f', 'ip', 'connection', 'status', 'id', network_name]
            # We are only interested in the first line of this output.
            #   It should look something like this:
            #   IP4.ADDRESS[1]:ip = 255.255.255.255/255, gw = 255.255.255.255
            ip_line = subprocess.check_output(nmcli_command).split('\n')[0]
            gateway_ip = ip_line.split()[5]

        else:
            # TODO: Test this if we care enough to. I can't test this on this system either.
            nmcli_command = ['nmcli', '-t', '-f', 'ip4.gateway', 'connection', 'show', network_name]
            ip_raw = subprocess.check_output(nmcli_command).split(':')[1]
            gateway_ip = ip_raw.replace('\n', '')

        self.logger.trace('get_gateway_ip: Gateway IP for %s is %s.' % (network_name, gateway_ip))

        return gateway_ip
