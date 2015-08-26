#!/usr/bin/env python2
import dns.resolver
import random
import subprocess
import os
import time
import timber

# Depends on dig, usually in the dnsutils package
# Depends on python-dnspython


class checker:
    def __init__(self, wired_network_name, wifi_network_names, nameservers, queries, dig_timeout=10, nmcli_timeout=20):
        #TODO: value checking?
        self.wired_network_name = wired_network_name
        self.wifi_network_names = wifi_network_names
        self.nameservers = nameservers
        self.queries = queries
        self.nmcli_timeout = nmcli_timeout
        self.dig_timeout = dig_timeout


        self.logger = timber.get_instance()

        self.logger.trace('Getting NetworkManager version...')
        raw_version = subprocess.check_output([ 'nmcli', '--version' ])
        version_string = raw_version.split()[3]
        self.nm_version = int(version_string.split('.')[0])

        self.logger.trace('Using NetworkManager major version ' + str(self.nm_version))

        self.devnull = open(os.devnull, 'w')
    ### END def __init__

    def _query(self, iface_ip, gateway_ip, nameserver, query):
        # Attempt a DNS query, return true for success, false for failure
        # Assume it doesn't work
        success = False
        self.logger.debug('Adding route to routing table.')
        if subprocess.check_output([ 'ip', 'route', 'replace', nameserver + '/32', 'via', gateway_ip ]) != '':
            # If this fails, the query results may give us a false positive
            self.logger.error('Adding route failed!')
        else:
            self.logger.debug('Adding route successful.  Starting actual query.')
            time.sleep(1)
            if subprocess.call([ 'dig', '@' + nameserver, '-b', iface_ip, query, '+time=' + str(self.dig_timeout) ], stdin=self.devnull, stdout=self.devnull, stderr = self.devnull) != 0:
                success = False
            else:
                success = True

        # Remove the route we made
        subprocess.call([ 'ip', 'route', 'del', nameserver ], stdin=self.devnull, stdout=self.devnull, stderr = self.devnull)
        return success
    ### END def _query

    def _DNS_works(self, nm_name):
        self.logger.info('Checking network ' + nm_name)
        # TODO: Determine version using this
        # nmcli --version | awk '{print substr($4,1,1)}'

        if self.nm_version >= 1:
            ### for NetworkManager 1.0+
            #self.logger.info('NetworkManager is newer than 1.0.')
            gateway_string = subprocess.check_output([ 'nmcli', '-t', '-f', 'ip4.gateway', 'c', 's', nm_name ])
            gateway_ip_raw = gateway_string.split(':')[1]
            gateway_ip = gateway_ip_raw.replace('\n', '')

            iface_string = subprocess.check_output([ 'nmcli', '-t', '-f', 'ip4.address', 'c', 's', nm_name ])
            iface_ip_raw = iface_string.split(':')[1]
            iface_ip = iface_ip_raw.split('/')[0]
            ### end NM 1.0+
        elif self.nm_version < 1:
            # ugly-ass text parsing for NM 0.x goes here
            # TODO: use the following command for networkmanager pre-1.0
            # nmcli -t -f ip c s id "The Wired" | grep ADDRESS | awk '{print $6}'
            self.logger.warn('NetworkManager is pre-1.0.  You should update.')
            nm_info = subprocess.check_output( ['nmcli', '-t', '-f', 'ip', 'c', 's', 'id', nm_name ])
            ip_line = nm_info.split('\n')[0]
            gateway_ip = ip_line.split()[5]

            iface_ip_raw = ip_line.split()[2]
            iface_ip = iface_ip_raw.split('/')[0]

            # Assume it doesn't work
            works = False

            nameserver = random.sample(self.nameservers, 2)
            query = random.sample(self.queries, 2)

            self.logger.trace('Querying ' + nameserver[0] + ' for ' + query[0] + ' via ' + gateway_ip + '...')
            self.logger.debug('Trying first DNS query.')
        if self._query(iface_ip, gateway_ip, nameserver[0], query[0]):
            self.logger.debug('First query succeeded!')
            works = True
        else:
            self.logger.warn('First query failed!')
            self.logger.debug('Trying second DNS query.')
            self.logger.trace('Querying ' + nameserver[1] + ':' + query[1] + ' via ' + gateway_ip + '...')

            if self._query( iface_ip, gateway_ip,  nameserver[1], query[1] ):
                self.logger.debug('Second query succeeed!')
                works = True
            else:
                self.logger.warn('Second query failed!')
                self.logger.trace('Giving up on network ' + nm_name)
        return works
    ### END def _DNS_works

    def _is_network_up(self, nm_name):
        if nm_name in subprocess.check_output([ 'nmcli', 'c', 's' ]):
            self.logger.debug(nm_name + ' is up.')
            return self._DNS_works(nm_name)
        else:
            self.logger.warn(nm_name + ' is down.')
            return False
        pass
    ### END def _is_network_up

    def _wifi_dance(self):
        connected_network = ''
        for net in self.wifi_network_names:
            connect_success = False
            self.logger.info('Trying to connect to ' + net)
            if self.nm_version == 0:
                self.logger.trace('Accomodating for your old software.')
                connect_success = subprocess.call([ 'nmcli', 'c', 'up', 'id', net, '--timeout', str(self.nmcli_timeout) ], stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)

            elif self.nm_version >= 1:
                self.logger.trace('Using shiny new NetworkManager stuff.')
                connect_success = subprocess.call([ 'nmcli', '-w', str(self.nmcli_timeout), 'c', 'up', net ], stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)
            ### END if self.nm_version

            if connect_success == 0:
                self.logger.info('Connected to ' + net + '.  Checking DNS.')
                if self._is_network_up(net):
                    self.logger.debug(net + ' is connected with good DNS.')
                    connected_network = net
                else:
                    self.logger.warn(net + ' connected but failed DNS check.')
            else:
                self.logger.warn('Could not connect to ' + net)
            ### END if connect_success

        return connected_network
    ### END def _wifi_dance

    def check_loop(self):
        # TODO: Work out network check timing
        # TODO: Add sigterm handling method
        self.logger.debug('Starting network loop.')
        
        connected_network = ''
        for net in self.wifi_network_names:
            if self._is_network_up(net):
                connected_network = net
                self.logger.debug(connected_network + ' is up.')
                break
            while connected_network == '':
                self.logger.warn('No networks are up!  Do the wifi dance!')
                self.logger.info('Trying all listed networks.')
                connected_network = self._wifi_dance()
                if self._is_network_up(self.wired_network_name):
                    self.logger.info('Wired network is up, disconnecting wifi.')
                    if connected_network != '':
                        # Disconnect wifi so we can connect to a higher priority network later
                        disconnect_success = False
                        if self.nm_version == 0:
                            disconnect_success = subprocess.call([ 'nmcli', '--timeout', 'c', 'down', 'id', connected_network, str(self.nmcli_timeout )], stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)
                        elif self.nm_version >=1:
                            disconnect_success = subprocess.call([ 'nmcli', '-w', str(self.nmcli_timeout), 'c', 'down', connected_network ], stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)
                        if disconnect_success == 0:
                            self.logger.trace('Network ' + connected_network + ' disconnected properly.')
                        else:
                            self.logger.trace('Network ' + connected_network + ' failed to disconnect, it\'s probably already down.')
                    connected_network = self.wired_network_name
                else:
                    self.logger.warn('Wired network failed to connect a second time.')
                if connected_network == '':
                    self.logger.error('All networks failed to connect, retrying the loop.')
            else:
                self.logger.debug('Wired network is up, nothing to do.')
            sleep_time = random.randrange(150)
            self.logger.trace('Sleeping for ' + str(sleep_time) + ' seconds.')
            time.sleep(sleep_time)
        pass
    ### END def check_loop
### END class checker
