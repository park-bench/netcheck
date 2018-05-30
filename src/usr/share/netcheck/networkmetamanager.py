# Copyright 2015-2017 Joel Allen Luellwitz and Andrew Klapp
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

__all__ = ['NetworkMetaManager']
__author__ = 'Joel Luellwitz and Andrew Klapp'
__version__ = '0.8'

import logging
import os
import re
import subprocess


# Not making issues for any other TODOs in this file because it is deleted in a pull request.
# TODO #14: Use the network manager API instead.
class NetworkMetaManager:
    """NetworkMetaManager provides an easy to work with interface for some of
    NetworkManager's basic functions. It uses the 'nmcli' command and supports NetworkManager
    version 0.x.
    """

    def __init__(self, nmcli_timeout):

        self.logger = logging.getLogger()

        # Set timeouts
        self.nmcli_timeout = nmcli_timeout

        # Get NetworkManager major version and dump it to self.major_version.
        #   nmcli parameters changed between 0.x and 1.x.
        # TODO: Does the program bail if this command fails?
        raw_version = subprocess.check_output(['nmcli', '--version'])
        version_string = raw_version.split()[3]
        major_version = int(version_string.split('.')[0])

        # This version of NetworkMetaManager only works with Network Manager 0.x.
        if major_version > 0:
            error_message = 'Invalid Network Manager version %d.' % major_version
            self.logger.critical(error_message)
            raise Exception(error_message)

        # Easy and efficient /dev/null access
        self.devnull = open(os.devnull, 'w')

        # Compile the regexes for grabbing addresses
        # TODO: Eventually handle Network Manager v1.x output.
        # Expected output for Network Manager v0.x
        #   IP4.ADDRESS[1]:ip = 255.255.255.255/255, gw = 255.255.255.255
        self.interface_ip_v0_regex = re.compile(
            'IP4.ADDRESS\[1\]:ip = (?P<interface_ip>.+)/[0-9]{1,3}, gw = .+')
        self.gateway_ip_v0_regex = re.compile(
            'IP4.ADDRESS\[1\]:ip = .+ gw = (?P<gateway_ip>.+)')

        ip_octet_pattern = '[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]'
        self.valid_ip_regex = re.compile(
            '^(?P<ip>((%s)\.){3}(%s))$' % (ip_octet_pattern, ip_octet_pattern))

    def _subprocess_call(self, command_list):
        """Invokes a program on the system.
        Param command_list is a command split into a list, not a list of separate commands.
        Returns True upon success, False otherwise.
        """
        exit_code = None

        self.logger.trace('_subprocess_call: Calling "%s".' % ' '.join(command_list))
        try:
            # Run command with subprocess.call, redirecting output to /dev/null.
            exit_code = subprocess.call(command_list, stdin=self.devnull,
                                        stdout=self.devnull, stderr=self.devnull)
            self.logger.trace('_subprocess_call: Subprocess returned code %d.' % exit_code)
        except subprocess.CalledProcessError:
            # Eat exceptions because it will properly return False this way.
            # TODO: Log full CalledProcessError.
            self.logger.error('Subprocess call failed!')

        return exit_code == 0

    def connect(self, network_name):
        """Try to connect to a network. Returns True on success, False on failure."""

        nmcli_command = ['nmcli', 'connection', 'up', 'id', network_name, '--timeout',
                         '%d' % self.nmcli_timeout]
        connect_success = self._subprocess_call(nmcli_command)

        if connect_success:
            self.logger.trace('connect: Connected to %s.' % network_name)

        else:
            self.logger.debug('connect: Could not connect to %s.' % network_name)

        return connect_success

    def disconnect(self, network_name):
        """Try to disconnect a network. Returns True on success, False on failure."""

        # Disconnecting does not accept a timeout option, apparently.
        #   This is not a problem because none of our code uses this method anyway.
        nmcli_command = ['nmcli', 'connection', 'down', 'id', network_name]
        disconnect_success = self._subprocess_call(nmcli_command)

        if disconnect_success:
            self.logger.trace('disconnect: Disconnected from %s.' % network_name)
        else:
            self.logger.debug('disconnect: Disconnecting from %s failed!' % network_name)

        return disconnect_success

    def is_connected(self, network_name):
        """Check for network connectivity, not including DNS. Returns True if connected,
        False otherwise.
        """
        is_connected = False

        self.logger.trace('is_connected: Checking connectivity for %s.' % network_name)

        nmcli_command = ['nmcli', 'c', 's']

        # See if Network Manager is connected or connecting to the network.
        # TODO: Does this work right if the network name you are searching for is
        #   a subset of another network name?
        is_active = network_name in subprocess.check_output(nmcli_command)
        # See if we have an IP to distinguish between connected and connecting.
        # TODO: Since these two commands are not atomic, we have a race condition.

        if is_active:
            has_ip = not(self.get_interface_ip(network_name) is None)
            if has_ip:
                self.logger.trace('is_connected: Connected to %s.' % network_name)
                is_connected = True
            else:
                self.logger.trace('is_connected: %s does not have an IP address.' %
                                  network_name)
        else:
            self.logger.trace('is_connected: Not connected to %s.' % network_name)

        return is_connected

    def get_interface_ip(self, network_name):
        """Get the current IP address for network_name's interface. Returns None if there is
        no connection.
        """
        self.logger.trace('get_interface_ip: Getting interface IP for %s.' % network_name)

        interface_ip = None

        # We are only interested in the first line of this output.
        #   It should look something like this:
        #   IP4.ADDRESS[1]:ip = 255.255.255.255/255, gw = 255.255.255.255
        nmcli_command = ['nmcli', '-t', '-f', 'ip', 'connection', 'status', 'id',
                         network_name]

        try:
            nmcli_output = subprocess.check_output(nmcli_command)
        except subprocess.CalledProcessError:
            # If the nmcli command returns non-zero, it will not return the right
            #   data anyway.
            # TODO: Log the CalledProcessError as at least debug.
            nmcli_output = ''

        regex_match = self.interface_ip_v0_regex.search(nmcli_output)

        if regex_match:
            raw_ip = regex_match.group('interface_ip')
            valid_ip = self.valid_ip_regex.search(raw_ip)
            if valid_ip:
                interface_ip = valid_ip.group('ip')
            else:
                self.logger.debug('get_interface_ip: IP address was found, but is invalid.')
        else:
            self.logger.debug('get_interface_ip: IP address not found.')

        self.logger.trace('get_interface_ip: Interface IP for %s is %s.' %
                          (network_name, interface_ip))

        return interface_ip
