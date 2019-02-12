# Copyright 2015-2019 Joel Allen Luellwitz and Andrew Klapp
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

__all__ = ['NetworkManagerHelper']
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

SERVICE_UNKNOWN_MAX_DELAY = 1  # In seconds.
SERVICE_UNKNOWN_MAX_ATTEMPTS = 3
VANISHED_SYMBOL_MAX_ATTEMPTS = 3

NETWORKMANAGER_ACTIVATION_CHECK_DELAY = 0.1

NM_CONNECTION_ACTIVATING = "NM_CONNECTION_ACTIVATED"
NM_CONNECTION_ACTIVATED = "NM_CONNECTION_ACTIVATED"
NM_CONNECTION_DISCONNECTED = "NM_CONNECTION_DISCONNECTED"

SERVICE_UNKNOWN_PATTERN = re.compile(
    r'^org\.freedesktop\.DBus\.Error\.ServiceUnknown:')
UNKNOWN_METHOD_PATTERN = re.compile(
    r'org.freedesktop.DBus.Error.UnknownMethod: No such interface '
    r"'org.freedesktop.DBus.Properties' on object at path ")

def reiterative(method):
    """Repeatedly retries a method if it throws certain types of exceptions. Specifically,
    will retry if it is detected that NetworkManager is not running or if a NetworkManager
    method or property is temporarily not available. If NetworkManger is not running, this
    decorator will retry the method until a specified period of time has elapsed AND a
    minimum number of attempts have been made. (Waiting for NetworkManager to restart.) For
    missing NetworkManager methods or properties, this decorator will retry the method until
    a minimum number of attempts have been made. (Waiting for method or property to
    reappear.) When this decorator stops retrying a method and the last invocation fails,
    this decorator allows the last exception raised to pass through to the caller.

    The retry mechanism is only applied on the first instance of this decorator on the call
    stack. Subsequent instances simply pass through to the called method.

    method: A reference to the method being decorated.
    """
    def passthrough_on_reentry(self, *args, **kwargs):
        """Ensures this decorator is only applied on the first instance of this decorator on
        the call stack. Subsequent instances simply pass through to the called method.

        self: A reference to a class instance (the object).
        args: A tuple of the method's positional arguments.
        kwargs: A dictionary of the method's keyword arguments.
        """
        stack_trace = traceback.extract_stack()
        current_frame = stack_trace[-1]
        in_decorator = False
        for frame in stack_trace[:-1]:
            if frame[0] == current_frame[0] and frame[3] == current_frame[3]:
                in_decorator = True

        return_value = None
        if in_decorator:
            return_value = method(self, *args, **kwargs)
        else:
            return_value = _retry_on_exceptions(self, *args, **kwargs)

        return return_value

    def _retry_on_exceptions(self, *args, **kwargs):
        """Repeatedly retries 'method' if it throws certain types of exceptions. See the
        decorator documentation for specific behavior.

        self: A reference to a class instance (the object).
        args: A tuple of the method's positional arguments.
        kwargs: A dictionary of the method's keyword arguments.
        """
        method_start_time = datetime.datetime.now()
        delay_from_service_unknown = 0
        service_unknown_count = 0
        vanished_symbol_count = 0
        finished = False
        return_value = None
        while not finished:
            try:
                return_value = method(self, *args, **kwargs)
                finished = True
            except DBusException as exception:
                if SERVICE_UNKNOWN_PATTERN.match(str(exception)):
                    if service_unknown_count == 0:
                        self.logger.warning(
                            'ServiceUnknown exception detected. NetworkManager might be '
                            'restarting. Will retry for %s seconds. %s: %s',
                            SERVICE_UNKNOWN_MAX_DELAY, type(exception).__name__,
                            str(exception))

                    service_unknown_count += 1
                    NetworkManagerHelper.NetworkManager.SignalDispatcher.handle_restart(
                        'org.freedesktop.NetworkManager', 'please', 'work')
                    new_method_start_time = datetime.datetime.now()
                    delay_since_last_attempt = (
                        new_method_start_time - method_start_time).total_seconds()
                    delay_from_service_unknown += delay_since_last_attempt
                    method_start_time = new_method_start_time
                    if service_unknown_count < SERVICE_UNKNOWN_MAX_ATTEMPTS \
                            or delay_from_service_unknown < SERVICE_UNKNOWN_MAX_DELAY:
                        time.sleep(max(.1 - delay_since_last_attempt, 0))
                    else:
                        self.logger.error(
                            'Service unknown after %d attempts and %f seconds. %s: %s',
                            service_unknown_count, delay_from_service_unknown,
                            type(exception).__name__, str(exception))
                        raise

                elif UNKNOWN_METHOD_PATTERN.match(str(exception)):
                    vanished_symbol_count += 1
                    if vanished_symbol_count >= VANISHED_SYMBOL_MAX_ATTEMPTS:
                        self.logger.error(
                            'Method was unknown after %d retry attempts. %s: %s',
                            vanished_symbol_count, type(exception).__name__,
                            str(exception))
                        raise
                else:
                    raise

            except NetworkManagerHelper.ObjectVanished as exception:
                vanished_symbol_count += 1
                if vanished_symbol_count >= VANISHED_SYMBOL_MAX_ATTEMPTS:
                    self.logger.error(
                        'Object vanished after %d retry attempts. %s: %s',
                        vanished_symbol_count, type(exception).__name__, str(exception))
                    raise

        return return_value

    return passthrough_on_reentry

class NetworkManagerHelper(object):
    """NetworkManagerHelper abstracts away some of the messy details of the NetworkManager
    D-Bus API. All methods will retry for a bit when encounting exceptions that the
    NetworkManager API frequently throws.
    """
    # TODO: Eventually remove this non-sense once we implement propper logging. (Yes, this is
    #   all to support our logger as an instance variable.) (gpgmailer issue 18)
    NetworkManager = None
    ObjectVanished = None

    def __init__(self, config):
        """Constructor.

        config: The configuration dictionary constructed during program initialization.
        """

        self.logger = logging.getLogger(__name__)
        self.connection_activation_timeout = config['connection_activation_timeout']
        self.connection_ids = config['connection_ids']

        self.random = random.SystemRandom()

        self._import_network_manager()

    @reiterative
    def get_all_connection_ids(self):
        """Returns all connection IDs known to NetworkManager."""
        connection_ids = []
        for connection in self.NetworkManager.Settings.ListConnections():
            connection_ids.append(connection.GetSettings()['connection']['id'])

        return connection_ids

    @reiterative
    def update_available_connections(self):
        """Updates the list of connections that NetworkManager can activate. Currently,
        this is implemented by doing a WiFi scan.
        """
        for device in self.NetworkManager.NetworkManager.GetDevices():
            if hasattr(device.SpecificDevice(), "RequestScan") and callable(
                    device.SpecificDevice().RequestScan):
                try:
                    device.SpecificDevice().RequestScan({})
                except DBusException as exception:
                    # This is logged as debug because it occurs so frequently.
                    self.logger.debug(
                        'update_available_connections: An error occurred while requesting '
                        'scan from device %s. %s: %s', device.Interface,
                        type(exception).__name__, str(exception))
                    self.logger.debug(traceback.format_exc())

    @reiterative
    def activate_connections_quickly(self, connection_ids):
        """Activates a list of connections in order without waiting to see if each activation
        was successful (obtains an IP address in the subnet of a gateway). The method returns
        once an activation attempt has been made with each network device or when there are
        no more connection IDs left to process. This method is intended to be used when the
        program first starts to ensure access to the Internet is established as quickly as
        possible.

        connection_ids: A list of NetworkManager connection IDs to activate in preferred
          order.
        """

        # Create a connection to device multi-map.
        connection_devices_dict = {}
        for device in self.NetworkManager.NetworkManager.GetDevices():
            # See if the connection is already activated.
            applied_connection = self._get_applied_connection(device)
            if not applied_connection \
                    or applied_connection['connection']['id'] not in connection_ids:
                for connection in device.AvailableConnections:
                    available_connection_id = connection.GetSettings()['connection']['id']
                    if available_connection_id in connection_ids:
                        if connection_devices_dict.get(connection, None) is None:
                            connection_devices_dict[connection] = []
                        connection_devices_dict[connection].append(device)

        used_devices = []
        for connection in connection_devices_dict:

            # Try to activate the connection with a random available device.
            connection_devices = connection_devices_dict[connection]
            for used_device in used_devices:
                connection_devices.remove(used_device)
            if connection_devices:
                device = connection_devices[self.random.randint(
                    0, len(connection_devices) - 1)]

                # '/' means pick an access point automatically (if applicable).
                self.NetworkManager.NetworkManager.ActivateConnection(
                    connection, device, '/')

                used_devices.append(device)

    # Note: A helper method is reiterative instead.
    def activate_connection_and_steal_device(self, connection_id,
                                             excluded_connection_ids=None):
        """Activates a specific connection, stealing network devices from other connections
        if no network device is available. An activation is only considered successful if it
        is assigned an IP that is associated with a gateway.

        connection_id: The displayed name of the connection in NetworkManager to activate.
        excluded_connection_ids: A list of NetworkManager connection IDs that the specified
          connection cannot steal a network device from.
        Returns a tuple. The first value is either true or false indicating whether the
          connection was successful. The second value is a String indicating which connection
          was stolen. None is returned for the second value if no connection was stolen.
        """
        stolen_connection_ids = set()
        success = self._reiterative_activate_connection_and_steal_device(
            connection_id, stolen_connection_ids, excluded_connection_ids)
        return success, list(stolen_connection_ids)

    @reiterative
    def activate_connection_with_available_device(self, connection_id):
        """Activates a specific connection if an associated network device is available. If
        more than one network device is available, one is randomly chosen. An activation is
        only considered successful if it is assigned an IP that is associated with a gateway.

        connection_id: The displayed name of the connection in NetworkManager to activate.
        Returns True if the connection is activated, False otherwise.
        """
        success = False

        # Get a list of all devices this connection can be applied to.
        available_devices = []
        connection = None
        for device in self.NetworkManager.NetworkManager.GetDevices():
            # See if the connection is already activated.
            applied_connection = self._get_applied_connection(device)
            if applied_connection \
                    and applied_connection['connection']['id'] == connection_id:
                # The connection is already activated.
                # I do hate multiple returns but this does seem the most Pythonic.
                return self._wait_for_gateway_ip(applied_connection)
            elif not applied_connection \
                    or applied_connection['connection']['id'] not in self.connection_ids:
                for available_connection in device.AvailableConnections:
                    if available_connection.GetSettings()['connection']['id'] \
                            == connection_id:
                        connection = available_connection
                        available_devices.append(device)

        if connection is None:
            self.logger.debug('activate_connection_with_available_device: Connection "%s" '
                              'is not available.', connection_id)
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
                self.NetworkManager.NetworkManager.ActivateConnection(
                    connection, available_device, '/')
                success = self._wait_for_gateway_ip(connection.GetSettings())

        return success

    @reiterative
    def deactivate_connection(self, connection_id):
        """Deactivates the specified connection.

        connection_id: The displayed name of the connection in NetworkManager to deactivate.
        """
        active_connection = None
        for device in self.NetworkManager.NetworkManager.GetDevices():
            # See if the connection is already activated.
            if device.ActiveConnection and device.ActiveConnection.Connection.GetSettings()[
                    'connection']['id'] == connection_id:
                active_connection = device.ActiveConnection
                break

        if not active_connection:
            self.logger.warning('Could not find active connection %s.', connection_id)
        else:
            self.NetworkManager.NetworkManager.DeactivateConnection(active_connection)

    @reiterative
    def get_connection_ip(self, connection_id):
        """Attempts to retrieve the IP address associated with the given connection's
        gateway. If the IP address is unable to be retrieved, None is returned.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns the IP address as a string if it can be retrieved. Returns None otherwise.
        """

        # TODO: Add IPv6 support. (issue 19)
        ip_address = None

        if not self.connection_is_activated(connection_id):
            self.logger.warning(
                'Attempted to get IP address for connection %s, which is not connected.',
                connection_id)

        else:
            connection_device = None
            for device in self.NetworkManager.NetworkManager.GetDevices():
                applied_connection = self._get_applied_connection(device)
                if applied_connection is not None \
                        and applied_connection['connection']['id'] == connection_id:
                    connection_device = device
                    break

            if connection_device is None:
                self.logger.debug('get_connection_ip: Connection "%s" has no IP.',
                                  connection_id)
            else:
                gateway_address = netaddr.IPNetwork(connection_device.Ip4Config.Gateway)

                for address_data in connection_device.Ip4Config.AddressData:
                    # Technically, according to the RFC, the IP portion of a CIDR should be
                    #   the first address in the CIDR. We'll ignore this.
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
        """Checks whether the connection with the given connection ID is activated.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns True if the connection is activated, False otherwise.
        """

        connection_is_activated = False

        connection_state = self._get_connection_activation_state(connection_id)

        if connection_state is NM_CONNECTION_ACTIVATED:
            connection_is_activated = True

        return connection_is_activated

    # TODO: Remove this method after we move to systemd. (issue 23)
    def _import_network_manager(self):
        """Imports the NetworkManager module and related modules with retry support. Retry
        support was added in case NetworkManager is restarting when this program starts.
        """
        try:
            import NetworkManager
            NetworkManagerHelper.NetworkManager = staticmethod(NetworkManager)
            from NetworkManager import ObjectVanished
            NetworkManagerHelper.ObjectVanished = staticmethod(ObjectVanished)
        except Exception as exception:
            self.logger.error(
                'Failed to import NetworkManager or ObjectVanished. Will retry in 10 '
                'seconds. %s: %s', type(exception).__name__, str(exception))
            self.logger.error(traceback.format_exc())
            time.sleep(10)
            try:
                import NetworkManager
                NetworkManagerHelper.NetworkManager = staticmethod(NetworkManager)
                from NetworkManager import ObjectVanished
                NetworkManagerHelper.ObjectVanished = staticmethod(ObjectVanished)
            except Exception as exception2:
                self.logger.error(
                    'Failed again to import NetworkManager or ObjectVanished. Will retry '
                    'one again in 30 seconds. %s: %s', type(exception2).__name__,
                    str(exception2))
                self.logger.error(traceback.format_exc())
                time.sleep(30)
                try:
                    import NetworkManager
                    NetworkManagerHelper.NetworkManager = staticmethod(NetworkManager)
                    from NetworkManager import ObjectVanished
                    NetworkManagerHelper.ObjectVanished = staticmethod(ObjectVanished)
                except Exception as exception3:
                    self.logger.error(
                        'Failed to import NetworkManager or ObjectVanished in 40 seconds. '
                        'This probably means the NetworkManager daemon failed to start. '
                        'Giving up! %s: %s', type(exception3).__name__, str(exception3))
                    raise

    @reiterative
    def _reiterative_activate_connection_and_steal_device(
            self, connection_id, stolen_connection_ids, excluded_connection_ids):
        """Helper method that performs most of the functionality of
        activate_connection_and_steal_device. See activate_connection_and_steal_device for a
        general description.

        connection_id: The displayed name of the connection in NetworkManager to activate.
        stolen_connection_ids: A list of NetworkManager connection IDs that network devices
          were stolen from. This parameter is used to return information to the caller.
        excluded_connection_ids: A list of NetworkManager connection IDs that the specified
          connection cannot steal a network device from.
        Returns True if the connection is activated, False otherwise.
        """
        success = False

        # Get a list of all devices this connection can be applied to.
        available_devices = []
        used_device_connection_dict = {}
        connection = None
        for device in self.NetworkManager.NetworkManager.GetDevices():
            # See if the connection is already activated.
            applied_connection = self._get_applied_connection(device)
            if applied_connection \
                    and applied_connection['connection']['id'] == connection_id:
                # The connection is already activated.
                # I do hate multiple returns but this does seem the most Pythonic.
                return self._wait_for_gateway_ip(applied_connection), []
            elif excluded_connection_ids is None or applied_connection is None \
                    or applied_connection['connection']['id'] not in excluded_connection_ids:
                for available_connection in device.AvailableConnections:
                    if available_connection.GetSettings()['connection']['id'] \
                            == connection_id:
                        connection = available_connection
                        if not applied_connection:
                            available_devices.append(device)
                        else:
                            used_device_connection_dict[device] = applied_connection[
                                'connection']['id']

        if connection is None:
            self.logger.debug('_reiterative_activate_connection_and_steal_device: '
                              'Connection "%s" is not available.', connection_id)
        else:
            # Try to activate the connection with a random available device.
            success = self._activate_with_random_devices(
                connection=connection, devices=available_devices,
                stolen_connection_ids=stolen_connection_ids,
                used_device_connection_dict=used_device_connection_dict)
            if not success:
                # Try to activate the connection with a random used device.
                used_devices = numpy.asarray(used_device_connection_dict.keys())
                success = self._activate_with_random_devices(
                    connection=connection, devices=used_devices,
                    stolen_connection_ids=stolen_connection_ids,
                    used_device_connection_dict=used_device_connection_dict)

        return success

    def _activate_with_random_devices(
            self, connection, devices, stolen_connection_ids, used_device_connection_dict):
        """Activates a connection with a random device until successful or there are no
        more devices left.

        connection: A NetworkManager API object representing a connection settings profile.
        devices: A list of NetworkManager API objects representing devices that can be
          activated with the connection.
        stolen_connection_ids: A list of NetworkManager connection IDs that network devices
          were stolen from. This parameter is used to return information to the caller.
        used_device_connection_dict: A mapping of NetworkManager devices to connection IDs
          representing which connection is associated with an active device.
        """
        success = False
        devices_left = len(devices)
        while not success and devices_left:
            random_index = self.random.randint(0, devices_left - 1)
            device = devices[random_index]
            devices[random_index] = devices[devices_left - 1]
            devices_left -= 1

            if device in used_device_connection_dict:
                stolen_connection_ids.add(used_device_connection_dict[device])

            # '/' means pick an access point automatically (if applicable).
            self.NetworkManager.NetworkManager.ActivateConnection(connection, device, '/')
            success = self._wait_for_gateway_ip(connection.GetSettings())

        return success

    def _get_applied_connection(self, device):
        """Returns the NetworkManager.Connection that is currently 'applied' to the supplied
        network device.

        device: A NetworkManager API object representing a device.
        Returns the applied connection or None if the device has no applied connection.
        """
        applied_connection = None
        if device.State == self.NetworkManager.NM_DEVICE_STATE_ACTIVATED:
            try:
                # 0 means no flags
                applied_connection, _ = device.GetAppliedConnection(0)
            except DBusException as exception:
                self.logger.error(
                    'Error getting applied connection for device %s. %s: %s',
                    device.Interface, type(exception).__name__, str(exception))
                self.logger.error(traceback.format_exc())

        return applied_connection

    def _wait_for_gateway_ip(self, connection):
        """Wait for the configured number of seconds for the supplied connection to obtain an
        IP that is associated with a gatway.

        connection: A NetworkManager.Connection object that is expected to be assigned an
          Internet accessible IP.
        Returns True if the connection is assigned an IP that is associated with a gateway.
          False otherwise.
        """
        success = False
        give_up = False
        connection_id = connection['connection']['id']
        time_to_give_up = time.time() + self.connection_activation_timeout

        self.logger.debug('_wait_for_gateway_ip: Waiting for connection "%s"...',
                          connection_id)
        while not success and not give_up:

            connection_state = self._get_connection_activation_state(connection_id)
            connection_ip = self.get_connection_ip(connection_id)

            if connection_ip:
                self.logger.debug('_wait_for_gateway_ip: Connection "%s" assigned IP %s.',
                                  connection_id, connection_ip)
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

    def _get_connection_activation_state(self, connection_id):
        """Reads the activation state of the connection identified by connection ID.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns a constant representing the current connection state. Possible values are:
          NM_CONNECTION_ACTIVATING, NM_CONNECTION_ACTIVATED, and NM_CONNECTION_DISCONNECTED.
        """
        state = NM_CONNECTION_DISCONNECTED

        active_connection = self._get_active_connection(connection_id)

        if active_connection is None:
            self.logger.debug('_get_connection_activation_state: Connection "%s" is not '
                              'activated.', connection_id)

        else:
            if hasattr(active_connection, 'State'):
                if active_connection.State \
                        is self.NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATING:
                    state = NM_CONNECTION_ACTIVATING
                if active_connection.State \
                        is self.NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATED:
                    state = NM_CONNECTION_ACTIVATED

            else:
                self.logger.error('Connection %s is no longer activated.',
                                  connection_id)

        return state

    def _get_active_connection(self, connection_id):
        """Finds the active connection object for a given connection ID.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns a NetworkManager.ActiveConnection object. If no matching object exists, None
          is returned.
        """
        matched_active_connection = None

        active_connections = self.NetworkManager.NetworkManager.ActiveConnections

        for active_connection in active_connections:
            if active_connection.Connection.GetSettings()[
                    'connection']['id'] == connection_id:
                self.logger.trace('_get_active_connection: Found that connection "%s" is '
                                  'active.', connection_id)
                matched_active_connection = active_connection
                break

        return matched_active_connection
