#!/usr/bin/env python2
import dns.resolver
import random
import subprocess
import os
import time
import timber

# Depends on dig, usually in the dnsutils package
# Depends on python-dnspython

# TODO: Rethink logging.

# TODO: Add some documentation.
class checker:
    # TODO: We should probably pass in a dict instead of having a million parameters.
    # TODO: I'm thinking we shouldn't have default values. They should only be specified in the configuration.
    def __init__(self, wired_network_name, wifi_network_names, nameservers, queries, dig_timeout=10, nmcli_timeout=20):
        #TODO: value checking?
        self.wired_network_name = wired_network_name
        self.wifi_network_names = wifi_network_names
        self.nameservers = nameservers
        self.queries = queries  # TODO: What this parameter does is not clear.
        self.nmcli_timeout = nmcli_timeout
        self.dig_timeout = dig_timeout


        self.logger = timber.get_instance()

        # TODO: Probably should quit with appropriate warning if Network Manager does not exist.
        # TODO: This might be impossible, but see if there is an API to grab the version.
        self.logger.debug('Getting NetworkManager version...')
        raw_version = subprocess.check_output([ 'nmcli', '--version' ])
        version_string = raw_version.split()[3]
        self.nm_version = int(version_string.split('.')[0]) # TODO: I guess I would explicitly state that this is only the major version.

        self.logger.info('Using NetworkManager major version %d.' % self.nm_version)

        # Used for stdin, stdout, and stderr when calling subprocesses.
        self.devnull = open(os.devnull, 'w')
    ### END def __init__

    # Attempt a DNS query, return true for success, false for failure
    def _query(self, iface_ip, gateway_ip, nameserver, query):
        # Assume it doesn't work
        success = False
        self.logger.debug('Adding route to routing table.')
        if subprocess.check_output([ 'ip', 'route', 'replace', '%s/32' % nameserver, 'via', gateway_ip ]) != '':
            # If this fails, the query results may give us a false positive
            self.logger.error('Adding route failed!')
        else:
            self.logger.debug('Adding route successful. Starting actual query.')
            # TODO: Make configurable? Reduce?
            # TODO: Add comment about why this is necessary.
            time.sleep(1)

            if subprocess.call([ 'dig', '@%s' % nameserver, '-b', iface_ip, query, '+time=%d' % self.dig_timeout ], stdin=self.devnull, stdout=self.devnull, stderr = self.devnull) != 0:
                # TODO: Probably shouldn't set to false again.
                success = False
            else:
                success = True

        # Remove the route we made
        subprocess.call(['ip', 'route', 'del', nameserver], stdin=self.devnull, stdout=self.devnull, stderr = self.devnull)
        return success
    ### END def _query

    def _DNS_works(self, nm_name):
        
        # Assume it doesn't work
        works = False
        
        self.logger.info('Checking network %s.' % nm_name)
        # TODO: Do we still need the following TODO?
        # TODO: Determine version using this
        # nmcli --version | awk '{print substr($4,1,1)}'

        # TODO: I would abstract all version specific code behind subprocess specific functions so coders
        #   don't get lost in these details. Actually, I would probably hide it behind a network manager class.
        # TODO: Do all your version checks in the same order.
        if self.nm_version >= 1:
            ### for NetworkManager 1.0+
            self.logger.trace('NetworkManager is newer than 1.0.')
            gateway_string = subprocess.check_output([ 'nmcli', '-t', '-f', 'ip4.gateway', 'c', 's', nm_name ])
            gateway_ip_raw = gateway_string.split(':')[1]
            gateway_ip = gateway_ip_raw.replace('\n', '')

            # TODO: This seesm to be the same command. Why are we executing it twice?
            iface_string = subprocess.check_output([ 'nmcli', '-t', '-f', 'ip4.address', 'c', 's', nm_name ])
            iface_ip_raw = iface_string.split(':')[1]
            iface_ip = iface_ip_raw.split('/')[0]
            ### end NM 1.0+
        elif self.nm_version < 1:
            # ugly-ass text parsing for NM 0.x goes here
            # TODO: Is the following TODO still needed?
            # TODO: use the following command for networkmanager pre-1.0
            # nmcli -t -f ip c s id "The Wired" | grep ADDRESS | awk '{print $6}'
            # TODO: This is in an inner loop. This will flood the logs. This warning should go in init code if anywhere.
            self.logger.warn('NetworkManager is pre-1.0. You should update.')
            nm_info = subprocess.check_output( ['nmcli', '-t', '-f', 'ip', 'c', 's', 'id', nm_name ])
            ip_line = nm_info.split('\n')[0]
            gateway_ip = ip_line.split()[5]

            iface_ip_raw = ip_line.split()[2]
            iface_ip = iface_ip_raw.split('/')[0]

        nameserver = random.sample(self.nameservers, 2)
        query = random.sample(self.queries, 2)

        self.logger.debug('Querying %s for %s via %s ...' % (nameserver[0], query[0], gateway_ip))
        self.logger.debug('Trying first DNS query.')

        if self._query(iface_ip, gateway_ip, nameserver[0], query[0]):
            self.logger.debug('First query succeeded!')
            works = True
        else:
            self.logger.warn('First query failed!')
            self.logger.debug('Trying second DNS query.')
            self.logger.debug('Querying %s for %s via %s ...' % (nameserver[1], query[1], gateway_ip))

            if self._query(iface_ip, gateway_ip, nameserver[1], query[1]):
                self.logger.debug('Second query succeeed!')
                works = True
            else:
                self.logger.warn('Second query failed!')
                self.logger.warn('Giving up on network %s.' % nm_name)

        return works
    ### END def _DNS_works

    def _is_network_up(self, nm_name):
        # TODO: Put inline comments explaining what these parameters mean.
        if nm_name in subprocess.check_output([ 'nmcli', 'c', 's' ]):
            self.logger.debug('%s is up.' % nm_name)
            return self._DNS_works(nm_name)
        else:
            self.logger.warn('%s is down.' % nm_name)
            return False

        # TODO: Do you really need 'pass' here?
        pass
    ### END def _is_network_up

    # TODO: Umm... funny but maybe be more descriptive.
    def _wifi_dance(self):
        connected_network = ''

        for net in self.wifi_network_names:
            connect_success = False
            self.logger.info('Trying to connect to %s.' % net)

            if self.nm_version == 0:
                self.logger.trace('Accomodating for your old software.')
                connect_success = subprocess.call([ 'nmcli', 'c', 'up', 'id', net, '--timeout', str(self.nmcli_timeout) ], stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)

            elif self.nm_version >= 1:
                self.logger.trace('Using shiny new NetworkManager stuff.')
                connect_success = subprocess.call([ 'nmcli', '-w', str(self.nmcli_timeout), 'c', 'up', net ], stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)
            ### END if self.nm_version

            if connect_success == 0:
                self.logger.debug('Connected to %s. Checking DNS.' % net)

                if self._is_network_up(net):
                    self.logger.info('%s is connected with good DNS.' % net)
                    connected_network = net
                else:
                    self.logger.warn('%s connected but failed DNS check.' % net)

            else:
                self.logger.warn('Could not connect to %s.' % net)
            ### END if connect_success

        return connected_network
    ### END def _wifi_dance

    # TODO: I am confused about the high level logic of this main loop.
    # TODO: Name this something more clear.
    def check_loop(self):
        # TODO: Work out network check timing
        self.logger.debug('Starting network loop.')
       
        connected_network = ''
        for net in self.wifi_network_names:

            if self._is_network_up(net):
                connected_network = net
                self.logger.debug('%s is up.' % connected_network)
                # TODO: I think I would avoid a break here and just do more nesting.
                break

            # TODO: I don't think this is indented correctly. I think this should be at the same level as the for loop above.
            while connected_network == '':
                self.logger.warn('No networks are up! Do the wifi dance!')
                self.logger.info('Trying all listed networks.')
                connected_network = self._wifi_dance()

                if self._is_network_up(self.wired_network_name):
                    self.logger.info('Wired network is up, disconnecting wifi.')

                    if connected_network != '':
                        # Disconnect wifi so we can connect to a higher priority network later
                        # TODO: Since you always set disconnect_success, probably better to init this to None.
                        disconnect_success = False

                        # TODO: When checking version, do <1 rather than == 0 to fill the gap between 0 and 1.
                        if self.nm_version == 0:
                            disconnect_success = subprocess.call([ 'nmcli', '--timeout', 'c', 'down', 'id', connected_network, str(self.nmcli_timeout )], stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)
                        elif self.nm_version >=1:
                            disconnect_success = subprocess.call([ 'nmcli', '-w', str(self.nmcli_timeout), 'c', 'down', connected_network ], stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)

                        if disconnect_success == 0:
                            self.logger.trace('Network %s disconnected properly.' % connected_network)
                        else:
                            self.logger.warn('Network %s failed to disconnect, it\'s probably already down.' % connected_network)

                    connected_network = self.wired_network_name
                else:
                    # TODO: This isn't a terribly popular thing to do, but I generally like to handle the error case first.
                    # TODO: I don't see where you are testing the wired network the first time.
                    self.logger.warn('Wired network failed to connect a second time.')

                if connected_network == '':
                    self.logger.error('All networks failed to connect, retrying the loop.')

            # TODO: What is this else for? Does this even run?
            else:
                self.logger.debug('Wired network is up, nothing to do.')

            # TODO: This should be configurable.
            sleep_time = random.randrange(150)
            self.logger.debug('Sleeping for %d seconds.' % sleep_time)
            time.sleep(sleep_time)

        # TODO: Do we need a 'pass' here? Does pass restart the method? Maybe use 'while(True)' instead?
        #   I guess I'm confused about why this will loop forever.
        pass
    ### END def check_loop
### END class checker
