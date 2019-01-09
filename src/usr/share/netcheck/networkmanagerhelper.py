# Copyright 2015-2018 Joel Allen Luellwitz and Andrew Klapp
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

"""NetworkManagerHelper provides a readable layer of abstraction for the
python-networkmanager class.
"""

__all__ = ['DeviceNotFoundException', 'UnknownConnectionIdException', 'NetworkManagerHelper']
__author__ = 'Andrew Klapp and Joel Allen Luellwitz'
__version__ = '0.8'

import logging
import random
import re
import datetime
import time
import traceback
from dbus import DBusException
import netaddr
import numpy
import NetworkManager
from NetworkManager import ObjectVanished

OBJECT_VANISHED_MAX_DELAY = .1  # In seconds.
SERVICE_UNKNOWN_MAX_DELAY = 1  # In seconds.

NETWORKMANAGER_ACTIVATION_CHECK_DELAY = 0.1

NM_CONNECTION_ACTIVATING = "NM_CONNECTION_ACTIVATED"
NM_CONNECTION_ACTIVATED = "NM_CONNECTION_ACTIVATED"
NM_CONNECTION_DISCONNECTED = "NM_CONNECTION_DISCONNECTED"

SERVICE_UNKNOWN_PATTERN = re.compile(
    r'^org\.freedesktop\.DBus\.Error\.ServiceUnknown:')

logger = logging.getLogger(__name__)

# TODO: Currently not used.
class DeviceNotFoundException(Exception):
    """Raised when an interface name passed to NetworkManagerHelper is not found."""

# TODO: Make sure this is still used somewhere.
class UnknownConnectionIdException(Exception):
    """Raised when a connection ID is requested, but it is not known."""

def reiterative(method):
    """ TODO: """
    def wrapped_method(self, *args, **kwargs):
        """ TODO: """
        stack_trace = traceback.extract_stack()
        current_frame = stack_trace[-1]
        in_decorator = False
        method_start_time = datetime.datetime.now()
        for frame in stack_trace[:-1]:
            if frame[0] == current_frame[0] and frame[3] == current_frame[3]:
                in_decorator = True

        return_value = None
        if in_decorator:
            method(self, *args, **kwargs)
        else:
            delay_from_service_unknown = 0
            delay_from_object_vanished = 0
            finished = False
            while not finished:
                try:
                    return_value = method(self, *args, **kwargs)
                    finished = True
                except DBusException as exception:
                    if not SERVICE_UNKNOWN_PATTERN.match(str(exception)):
                        raise exception
                    else:
                        if delay_from_service_unknown == 0:
                            logger.warning(
                                'ServiceUnknown exception detected. NetworkManager might be '
                                'restarting. Will retry for %s seconds. %s: %s',
                                SERVICE_UNKNOWN_MAX_DELAY, type(exception).__name__,
                                str(exception))

                        NetworkManager.SignalDispatcher.handle_restart(
                            'org.freedesktop.NetworkManager', 'please', 'work')
                        new_method_start_time = datetime.datetime.now()
                        delay_from_service_unknown += new_method_start_time \
                            - datetime.timedelta(seconds=method_start_time)
                        method_start_time = new_method_start_time
                        if delay_from_service_unknown < SERVICE_UNKNOWN_MAX_DELAY:
                            time.sleep(.1)
                        else:
                            logger.error('Service unknown for too long. %s: %s',
                                         type(exception).__name__, str(exception))
                            raise exception

                except ObjectVanished as exception:
                    if delay_from_object_vanished == 0:
                        logger.debug(
                            'ObjectVanished exception detected. Will retry for %s seconds. '
                            '%s: %s', OBJECT_VANISHED_MAX_DELAY, type(exception).__name__,
                            str(exception))

                    new_method_start_time = datetime.datetime.now()
                    delay_from_object_vanished += new_method_start_time \
                        - datetime.timedelta(seconds=method_start_time)
                    method_start_time = new_method_start_time
                    if delay_from_object_vanished < OBJECT_VANISHED_MAX_DELAY:
                        time.sleep(.01)
                    else:
                        logger.error('Object vanished for too long. %s: %s',
                                     type(exception).__name__, str(exception))
                        raise exception

        return return_value

    return wrapped_method

class NetworkManagerHelper(object):
    """NetworkManagerHelper abstracts away some of the messy details of the NetworkManager
    D-Bus API.
    """

    def __init__(self, config):
        """Initializes the module by storing references to device objects and assembling a
        dict of connection IDs.

        config: The configuration dictionary constructed during program initialization.
        """

        self.logger = logging.getLogger(__name__)
        self.connection_activation_timeout = config['connection_activation_timeout']
        self.connection_ids = config['connection_ids']

        self.random = random.SystemRandom()

    @reiterative
    def update_available_connections(self):
        """ TODO: """
        for device in NetworkManager.NetworkManager.GetDevices():
            # TODO: See if we even need hasattr.
            if hasattr(device.SpecificDevice(), "RequestScan") and callable(
                    device.SpecificDevice().RequestScan):
                try:
                    device.SpecificDevice().RequestScan({})
                except DBusException as exception:
                    self.logger.debug(
                        "An error occurred while requesting scan from device %s. %s: %s",
                        device.Interface, type(exception).__name__, str(exception))
                    self.logger.debug(traceback.format_exc())

    @reiterative
    def activate_connections_quickly(self, connection_ids):
        """ TODO: 
        Remember, the big difference here is we aren't waiting to see if the connection
        succeeded.
        """

        # Create a connection to device multi-map.
        connection_devices_dict = {}
        for device in NetworkManager.NetworkManager.GetDevices():
            # See if the connection is already activated.
            applied_connection = self._get_applied_connection(device)
            if not applied_connection \
                    or applied_connection['connection']['id'] not in connection_ids:
                for connection in device.AvailableConnections:
                    available_connection_id = connection.GetSettings()['connection']['id']
                    if available_connection_id in connection_ids:
                        if connection_devices_dict.get(connection, None) \
                                is None:
                            connection_devices_dict[connection] = []
                        connection_devices_dict[connection].append(device)

        used_devices = []
        for connection in connection_devices_dict:

            # Try to activate the connection with a random available device.
            connection_devices = numpy.asarray(connection_devices_dict[connection])
            for used_device in used_devices:
                connection_devices.remove(used_device)
            device = connection_devices[self.random.randint(0, len(connection_devices) - 1)]

            # '/' means pick an access point automatically (if applicable).
            NetworkManager.NetworkManager.ActivateConnection(connection, device, '/')

            used_devices.append(device)

    # TODO: Prefer devices that don't have a connection.
    @reiterative
    def activate_connection_and_steal_device(self, connection_id,
                                             excluded_connection_ids=None):
        """ TODO:
        Returns a tuple. The first value is either true or false indicating whether the
          connection was successful. The second value is a String indicating which connection
          was stolen. None is returned for the second value if no connection was stolen.
        """
        success = False

        # Get a list of all devices this connection can be applied to.
        available_device_connection_dict = {}
        connection = None
        # TODO: Do we need to do the proxy call after calling GetDevices?
        for device in NetworkManager.NetworkManager.GetDevices():
            # See if the connection is already activated.
            applied_connection = self._get_applied_connection(device)
            if applied_connection \
                    and applied_connection['connection']['id'] == connection_id:
                # The connection is already activated.
                # I do hate multiple returns but this does seem the most Pythonic.
                return True, None
            elif excluded_connection_ids is None or applied_connection is None \
                    or applied_connection['connection']['id'] not in excluded_connection_ids:
                for available_connection in device.AvailableConnections:
                    if available_connection.GetSettings()['connection']['id'] \
                            == connection_id:
                        connection = available_connection
                        available_device_connection_dict[device] = \
                            applied_connection['connection']['id'] if applied_connection \
                            else None

        stolen_connection_ids = []
        if connection is None:
            self.logger.debug('Connection %s is not available.', connection_id)
        else:
            # Try to activate the connection with a random available device.
            success = False
            available_devices = numpy.asarray(available_device_connection_dict.keys())
            devices_left = len(available_devices)
            while not success and devices_left:
                random_index = self.random.randint(0, devices_left - 1)
                available_device = available_devices[random_index]
                available_devices[random_index] = available_devices[devices_left - 1]
                devices_left -= 1

                # '/' means pick an access point automatically (if applicable).
                networkmanager_output = NetworkManager.NetworkManager.ActivateConnection(
                    connection, available_device, '/')
                # TODO: Do we need to run the proxy call? Is it appropriate to raise an
                #   exception?
                self._run_proxy_call(networkmanager_output)
                stolen_connection_ids.append(
                    available_device_connection_dict[available_device])
                success = self._wait_for_connection(connection)

        return success, stolen_connection_ids

    @reiterative
    def activate_connection_with_available_device(self, connection_id):
        """Tells NetworkManager to activate a connection with the supplied connection ID.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns True if the connection is activated, False otherwise.
        """
        success = False

        # Get a list of all devices this connection can be applied to.
        available_devices = []
        connection = None
        # TODO: Do we need to do the proxy call after calling GetDevices?
        for device in NetworkManager.NetworkManager.GetDevices():
            # See if the connection is already activated.
            applied_connection = self._get_applied_connection(device)
            if applied_connection \
                    and applied_connection['connection']['id'] == connection_id:
                # The connection is already activated.
                # I do hate multiple returns but this does seem the most Pythonic.
                return True
            elif not applied_connection \
                    or applied_connection['connection']['id'] not in self.connection_ids:
                for available_connection in device.AvailableConnections:
                    if available_connection.GetSettings()['connection']['id'] \
                            == connection_id:
                        connection = available_connection
                        available_devices.append(device)

        if connection is None:
            self.logger.debug('Connection %s is not available.', connection_id)
        else:
            # Try to activate the connection with a random available device.
            success = False
            devices_left = len(available_devices)
            while not success and devices_left:
                random_index = self.random.randint(0, devices_left - 1)
                available_device = available_devices[random_index]
                available_devices[random_index] = available_devices[devices_left - 1]
                devices_left -= 1

                # '/' means pick an access point automatically (if applicable).
                networkmanager_output = NetworkManager.NetworkManager.ActivateConnection(
                    connection, available_device, '/')
                # TODO: Do we need to run the proxy call? Is is propriate to raise an
                #   exception?
                self._run_proxy_call(networkmanager_output)
                success = self._wait_for_connection(connection)

        return success

    @reiterative
    def deactivate_connection(self, connection_id):
        """ TODO: """
        active_connection = None
        for device in NetworkManager.NetworkManager.GetDevices():
            # See if the connection is already activated.
            # TODO: if device.State == NetworkManager.NM_DEVICE_STATE_ACTIVATED:
            if device.ActiveConnection and device.ActiveConnection.Id == connection_id:
                active_connection = device.ActiveConnection
                break

        if not active_connection:
            self.logger.warning('Could not find active connection %s.', connection_id)
        else:
            NetworkManager.NetworkManager.DeactivateConnection(active_connection)
            # TODO: Call proxy object?

    @reiterative
    def get_all_connection_ids(self):
        """ TODO: """
        connection_ids = []
        # TODO: Do proxy call?
        for connection in NetworkManager.Settings.ListConnections():
            connection_ids.append(connection.GetSettings()['connection']['id'])

        return connection_ids

    @reiterative
    def get_connection_ip(self, connection_id):
        """Attempts to retrieve the IP address associated with the given connection's
        gateway.  If the IP address is unable to be retrieved, None is returned.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns the IP address as a string if it can be retrieved.  Returns None otherwise.
        """

        # TODO #19: Add IPv6 support.
        ip_address = None

        if not self.connection_is_activated(connection_id):
            self.logger.warning(
                'Attempted to get IP address for connection %s, which is not connected.',
                connection_id)

        else:
            connection_device = None
            for device in NetworkManager.NetworkManager.GetDevices():
                applied_connection = self._get_applied_connection(device)
                if applied_connection is not None \
                        and applied_connection['connection']['id'] == connection_id:
                    connection_device = device
                    break

            if connection_device is None:
                self.logger.debug('Connection %s has no ip.', connection_id)
            else:
                gateway_address = netaddr.IPNetwork(connection_device.Ip4Config.Gateway)

                for address_data in connection_device.Ip4Config.AddressData:
                    # TODO: Verify this bad CIDR notation works. (The IP portion should be
                    #   the first address in the CIDR.)
                    address_cidr = '%s/%s' % (
                        address_data['address'], address_data['prefix'])
                    address_network = netaddr.IPNetwork(address_cidr)

                    if gateway_address in address_network:
                        ip_address = address_data['address']
                        break

                if ip_address is None:
                    self.logger.warning(
                        'No IP addresses for connection %s associated with gateway %s.',
                        connection_id, gateway_address)

        return ip_address

    @reiterative
    def connection_is_activated(self, connection_id):
        """Check whether the connection with the given connection ID is activated.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns True if the connection is activated, False otherwise.
        """

        connection_is_activated = False

        connection_state = self._get_connection_state(connection_id)

        if connection_state is NM_CONNECTION_ACTIVATED:
            connection_is_activated = True

        return connection_is_activated

    def _get_applied_connection(self, device):
        """ TOOD: """
        applied_connection = None
        if device.State == NetworkManager.NM_DEVICE_STATE_ACTIVATED:
            try:
                # 0 means no flags
                applied_connection, _ = device.GetAppliedConnection(0)
            except DBusException as exception:
                self.logger.error(
                    'Error getting applied connection for device %s. %s: %s',
                    device.Interface, type(exception).__name__, str(exception))
                self.logger.error(traceback.format_exc())

        return applied_connection

    def _wait_for_connection(self, connection):
        """Wait for the configured number of seconds for the specified active connection to
        finish activation.

        connection: The NetworkManager.Connection object to watch for connectivity.
        Return True if the connection is activated, False otherwise.
        """
        success = False
        give_up = False
        connection_id = connection.GetSettings()['connection']['id']
        time_to_give_up = time.time() + self.connection_activation_timeout

        self.logger.debug('Waiting for connection %s...', connection_id)
        while not success and not give_up:

            connection_state = self._get_connection_state(connection_id)
            connection_ip = self.get_connection_ip(connection_id)

            if not connection_ip:
                self.logger.debug('Connection %s assigned IP %s.', connection_id,
                                  connection_ip)
                success = True

            elif connection_state is NM_CONNECTION_DISCONNECTED:
                self.logger.warning('Connection %s disconnected. Trying next connection.',
                                    connection_id)
                give_up = True

            elif time.time() > time_to_give_up:
                self.logger.warning('Connection %s timed out. Trying next connection.',
                                    connection_id)
                give_up = True

            else:
                time.sleep(NETWORKMANAGER_ACTIVATION_CHECK_DELAY)

        return success

    def _get_connection_state(self, connection_id):
        """Reads the current state of the connection identified by the connection ID.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns a constant representing the current connection state.  Possible values are:
          NM_CONNECTION_ACTIVATING, NM_CONNECTION_ACTIVATED, and NM_CONNECTION_DISCONNECTED
        """
        state = NM_CONNECTION_DISCONNECTED

        active_connection = self._get_active_connection(connection_id)

        if active_connection is None:
            self.logger.debug('Connection %s is not activated.', connection_id)

        else:
            if hasattr(active_connection, 'State'):
                if active_connection.State \
                        is NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATING:
                    state = NM_CONNECTION_ACTIVATING
                if active_connection.State \
                        is NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATED:
                    state = NM_CONNECTION_ACTIVATED

            else:
                self.logger.error('Connection %s is no longer activated.',
                                  connection_id)

        return state

    def _get_active_connection(self, connection_id):
        """Finds the active connection object for a given connection ID.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns a NetworkManager.ActiveConnection object.  If no matching object exists, None
          is returned.
        """
        matched_active_connection = None

        active_connections = NetworkManager.NetworkManager.ActiveConnections
        self._run_proxy_call(active_connections)

        for active_connection in active_connections:
            if active_connection.Id == connection_id:
                self.logger.trace('Found that connection %s is active.',
                                  connection_id)
                matched_active_connection = active_connection
                break

        return matched_active_connection

    # TODO: Make sure this is really needed.
    def _run_proxy_call(self, proxy_call):
        """If proxy_call is callable, call it.

        Sometimes if NetworkManager enounters a critical error, it will return a callable
        that will raise an exception if called.  This error information is valuable, so
        raising this exception allows this program to get access to the error details.

        proxy_call: The output of a NetworkManager D-Bus call.
        """
        if callable(proxy_call):
            proxy_call()
