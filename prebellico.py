#!/usr/bin/python

import pcapy
import socket
import netifaces
import sys
import os
import re
import time
import sqlite3
import argparse
import logging
from datetime import datetime
from impacket import ImpactDecoder
from pcapy import findalldevs, open_live, PcapError
from operator import itemgetter
from itertools import groupby
from collections import defaultdict
import string
from pdb import set_trace as bp

####
#### Prebellico Functions Here
####


# Function to establish the name of the SQLite DB name, either as specified by the user, or using the default, and validating that it is a prebellico database which we can access.
def checkPrebellicoDb():
    sqliteDbFile=args['db']
    if sqliteDbFile is None:
        sqliteDbFile='prebellico.db'
    print("\nChecking for a '%s' database file.") % ( sqliteDbFile )
    if not os.path.exists(sqliteDbFile):
        print("\nThe '%s' database file does not exist. Creating a prebellico database now.") % ( sqliteDbFile )
        try:
            dbConnect=sqlite3.connect(sqliteDbFile)
            db=dbConnect.cursor()
            db.execute('create table prebellico(prebellicodb text)')
            db.execute('insert into prebellico values("prebellico_recon")')
            db.execute('create table HostIntelligence(number integer primary key, firstObserved text, lastObserved text, ipAddress text, macAddy text, hostname text, fqdn text, domain text, hostDescription text, dualHomed text, os text, hostType text, trustRelationships text, openTcpPorts text, openUdpPorts text, zombieIpid text, validatedSnmp text, validatedUsernames text, validatedPasswords text, credentials text, exploits text, permittedEgress text, discoveryInterface text, interfaceIp text)') 
            db.execute('create table NetworkIntelligence(id integer primary key, recordType text, data text, dateObserved text, associatedHost text, methodObtained text, sourceInterface text)')
            db.execute('create table TcpPushSessionTracking(number integer primary key, sourceIp text, sourcePort text, destIp text, destPort text)')
            db.execute('create table PrebellicoMeshNodes(id integer primary key, observerId text, role text, ipAddress text, connectionMethod text, networkEgress text, egressMethod text, c2Endpoint text, encryptionKey text)')
            db.execute('create table PrebellicoHostConfiguration(id integer primary key, executionDate text, flags text, interface text, ipAddress text, role text, c2Method text)')
            dbConnect.commit()
            print("\nThe '%s' prebellico database file has been created.") % ( sqliteDbFile )
            dbConnect.close()
        except sqlite3.OperationalError, msg:
            print msg
    else:
        print("\nThe '%s' database file exists. Working to confirm it's a prebellio database file and we have access to the database file.") % ( sqliteDbFile )
        try:
            dbConnect=sqlite3.connect(sqliteDbFile)
            db=dbConnect.cursor()
            db.execute('select * from prebellico')
            confirmPrebellicoDb=db.fetchone()[0]
            if confirmPrebellicoDb == "prebellico_recon":
                print("\nThe '%s' file is a prebellico database file.") % ( sqliteDbFile )
                dbConnect.close()
            else:
                print("\nThe '%s' file is not a prebellico database file:") % ( sqliteDbFile )
                print("\nPlease correct this issue and try again.")
                exit()
        except sqlite3.OperationalError, msg:
            print("\nThe '%s' file is not a prebellico database file:") % ( sqliteDbFile )
            print msg
            print("\nPlease correct this issue and try again.")
            exit()


# Function to open and close the DB, as well as return data as required
def prebellicoDb(queryType, statement, data):
    sqliteDbFile=args['db']
    if sqliteDbFile is None:
        sqliteDbFile='prebellico.db'
    dbConnect=sqlite3.connect(sqliteDbFile)
    db=dbConnect.cursor()

    # Test to see if the data is a single string/int or a list/tuple and execute a db function based upon determination to set the correct number of tokens.
    if isinstance(data, basestring) or isinstance(data, (int, long)):
        db.execute(statement, [data])
    else:
        dataListLength = len(data)
        db.execute(statement, data)

    # If the request is to read data from the DB, read the data from the DB.
    if queryType is 'readFromDb':
        returnData=db.fetchone()

    # If the request is to write data to the DB, post the data.
    elif queryType is 'writeToDb':
        dbConnect.commit()

     # If something else goes wrong, alter the user through STDIO.
    else:
        print("Something went wrong while trying to interact with the %s database via the %s function! The query type was '%s' and the data was '%s'.") % ( sqliteDbFile, queryType, data )
        exit()

    # Close the database connection and return data if a select statement was called
    dbConnect.close()
    if queryType is 'readFromDb':
        return(returnData)
    else:
        return


# Function to produce the time for database record keeping purposes. This is a function with intent to allow the user to sepecify how to create timestamps.
def timeStamp():
    #Obtain the current date/time in a standard format and return it
    now = datetime.now()
    return(str(now.strftime('%d%b%y %H:%M:%S')))


# Function to write data to the screen and prebellico log
def prebellicoLog(data):
    #Obtain the current date/time and write the message out to the log
    #now = datetime.now()
    logging.info(("\n%s %s") % (timeStamp(), data))
    return

# Because everyone needs a cool banner - shown by default unless someone asks for it to be disabled
def prebellicoBanner():
    banner = """
       ___          __       _____        
      / _ \_______ / /  ___ / / (_)______ 
     / ___/ __/ -_) _ \/ -_) / / / __/ _ \\
    /_/  /_/  \__/_.__/\__/_/_/_/\__/\___/
    """
    print(banner)
    time.sleep(1)
    print("\nThere is no patch for passive recon. ;)\n")
    time.sleep(2)


# Function to validate if an IP address is associated with an RFC1918 address or a known non-RFC1918 address space that a target site uses internally
def checkinternaladdress(networkIp):
    rfc1918addressregex = re.compile('^(127\.)|(192\.168\.)|(10\.)|(172\.1[6-9]\.)|(172\.2[0-9]\.)|(172\.3[0-1]\.)')#  Add this when IPv6 is ready: |(::1$)|([fF][cCdD])')
    networkMatch = rfc1918addressregex.match(networkIp)
    return(networkMatch)


# Function to create source and destination networks for known network tracking to assist future targeting.
def checkknownnetwork(networkIp, internalMatch):
    networkIpOctets = networkIp.split('.')
    knownNetworkCidr = networkIpOctets[0] + '.' + networkIpOctets[1] + '.' + networkIpOctets [2] + '.1/24'
    knownSourceNetwork = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "knownNet" and data=(?)', knownNetworkCidr)
    if knownSourceNetwork is None and internalMatch:
        prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, dateObserved, associatedHost, methodObtained, sourceInterface) values ("knownNet", ?, ?, ?, "passiveNetwork", ?)', [knownNetworkCidr, timeStamp(), networkIp, dev] )
        prebellicoLog(("-=-Network Recon-=-\nA new network has been identified: %s") % (knownNetworkCidr))
        newKnownNet = 1
    else:
        newKnownNet = 0
    return(newKnownNet)


# Function to detect the protcol used within the packet to steer accordingly.
def inspectproto(header, data):
        
        #If the user has set a timer to shift to a more agressive recon phase, check the timer around every fifteen minutes to see if a more agressive form of recon is required
        global initialReconUpdateTimeCheck
        global previousTrackUpdateTime
        if trackUpdateTime is not None:
            currentTrackUpdateTime = time.time()
            if initialReconUpdateTimeCheck == 0:
                previousTrackUpdateTime = time.time()
                initialReconUpdateTimeCheck = 1
            if ((int(round(previousTrackUpdateTime - currentTrackUpdateTime)/60)) == 15):
                print("\n\n\nPrebellico Recon Timer Update Status Check - Should only happen every 15 minutes, for about a minute.\n\n\n")
                previousTrackUpdateTime = time.time()
                prebellicoReconPhaseShiftStatus = checkPrebellicoWaitTimer()
                if prebellicoReconPhaseShiftStatus == 1:
                    Print("\n\n\n\nSpitting Hot Fire!!!\n\n\n")

	# Start to decode the packet, determine the protocol number and call the appropriate method.
	ethernetPacket = decoder.decode(data)
	protocolNumber = ethernetPacket.child().child().protocol
	if protocolNumber == 1:
		#print("\nThis is an ICMP packet.")
		icmpdiscovery(header,data)
		return
	elif protocolNumber == 4:
		#print("\nThis is an IP packet.")
		return
	elif protocolNumber == 6:
		#print("\nThis is a TCP packet.")
		# Pull TCP flags to determine tcp session state so that we can determine what TCP method to call for intel. 
		tcpSyn = ethernetPacket.child().child().get_SYN()
		tcpAck = ethernetPacket.child().child().get_ACK()
		tcpEce = ethernetPacket.child().child().get_ECE()
		tcpCwr = ethernetPacket.child().child().get_CWR()
		tcpFin = ethernetPacket.child().child().get_FIN()
		tcpPsh = ethernetPacket.child().child().get_PSH()
		tcpRst = ethernetPacket.child().child().get_RST()
		tcpUrg = ethernetPacket.child().child().get_URG()
		if ( tcpSyn == 1 and tcpAck == 1 ):
		    synackdiscovery(header,data)
                if ( tcpPsh == 1 and tcpAck == 1 or tcpAck == 1):
                    tcppushdiscovery(header,data)
		tcpdiscovery(header,data)
		return
	elif protocolNumber == 17:
		#print("\nThis is a UDP packet.")
		udpdiscovery(header,data)
		return
	elif protocolNumber == 41:
		#print("\nThis is an IPv6 encapulated packet.")
		return
	elif protocolNumber == 43:
		#print("\nThis is an IPv6 routing header packet.")
		return
	elif protocolNumber == 44:
		#print("\nThis is an IPv6 fragment header packet.")
		return
	elif protocolNumber == 58:
		#print("\nThis is an IPv6 ICMP packet.")
		return
	elif protocolNumber == 59:
		#print("\nThis is an IPv6 no next header packet.")
		return
	elif protocolNumber == 60:
		#print("\nThis is an IPv6 destination options packet.")
		return
	# This is not an accurate catchall and will more than likely fail at some point
	elif protocolNumber == None:
		#print("\nThis is not a supported IP packet.")
		return
	else:
		#print("\nThe protocol number in this packet is %s. This is not TCP.") % ( protocolnumber )
		#print("\nEnd of the inspectproto method.\n")
		return


# Function designed to sniff out intel tied to ICMP traffic
def icmpdiscovery(header,data):

	ethernetPacket = decoder.decode(data)
	protocolNumber = ethernetPacket.child().child().protocol
	if protocolNumber != 1:
    	    return
	ipHdr = ethernetPacket.child()
        macHdr = ethernetPacket
        sourceMac = macHdr.as_eth_addr(macHdr.get_ether_shost())
        destMac = macHdr.as_eth_addr(macHdr.get_ether_dhost())
        sourceIp = ipHdr.get_ip_src()
        destIp = ipHdr.get_ip_dst()
	icmpHdr = ethernetPacket.child().child()
        icmpType = icmpHdr.get_type_name(icmpHdr.get_icmp_type())

	# Work to determine if this is an icmp echo or echo reply. This is important, as it will allow us to determine if ICMP is permitted egress for C2 uses.
        if icmpType == "ECHO" or icmpType == "ECHOREPLY":
            
            # Work to determine if these are known internal IP addresses based upon RFC1918 or user supplied data.
            (sourceMatch, destMatch) = ( checkinternaladdress(sourceIp), checkinternaladdress(destIp) )

            # If a host does not match an RFC1918 address or a user specified internal address that an internal address is talking to, note the external host and the internal host permitted to talk to it and notify the user about the permitted connection.
            if not sourceMatch and destMatch:
                global icmpNetworkEgressPermitted
                if icmpNetworkEgressPermitted == 0:
                    prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterface) values ("egressMethod", "icmp", ?, "passiveNetwork", ?, ?)', [destIp, timeStamp(), dev] )
                    prebellicoLog("-=-Egress Recon-=-\nNetwork egress detected! Internal hosts are permitted to ping the internet.")
                    icmpNetworkEgressPermitted = 1

            # If the source host does match an RFC1918 address or a user specified internal address that an internal address is talking to, check to see if it belongs to any known nets.
            if sourceMatch:
                checkknownnetwork(sourceIp, sourceMatch)
                
                # See if the source host is stored in the DB in some way. If not, make a database record and alert the user.
                host = prebellicoDb('readFromDb', 'select * from HostIntelligence where ipAddress=(?)', sourceIp)
                if host is None:
                    prebellicoDb('writeToDb', 'insert into HostIntelligence (firstObserved,lastObserved, ipAddress, macAddy, discoveryInterface, interfaceIp) values (?,?,?,?,?,?)', [ timeStamp(), timeStamp(), sourceIp, sourceMac, dev, devip ] )
                    prebellicoLog(("-=-ICMP Recon-=-\nIdentified a host through ICMP(%s): %s") % ( icmpType, sourceIp ))
        return


# Function designed to sniff out intel tied to generic UDP intelligence such as SMB and SNMP traffic
def udpdiscovery(header,data):

	#print("\nStart of udpdiscovery method.\n")
	# Start to decode the packet and determine the protocol number. If not UDP, return as it does not apply here.
        ethernetPacket = decoder.decode(data)
        protocolNumber = ethernetPacket.child().child().protocol
        if protocolNumber != 17:
            return

	# Extract relevant data from the ethernet packet
	macHdr = ethernetPacket
	sourceMac = macHdr.as_eth_addr(macHdr.get_ether_shost())
	destMac = macHdr.as_eth_addr(macHdr.get_ether_dhost())
        ipHdr = ethernetPacket.child()
	udpHdr = ipHdr.child()
        sourceIp = ipHdr.get_ip_src()
        destIp = ipHdr.get_ip_dst()
	udpSourcePort = udpHdr.get_uh_sport()
	udpDestPort = udpHdr.get_uh_dport()
        tempData = udpHdr.get_data_as_string()

        # Work to determine if these are known internal IP addresses based upon RFC1918 or user supplied data.
        (sourceMatch, destMatch) = ( checkinternaladdress(sourceIp), checkinternaladdress(destIp) )

        # Look to see if the IP address appears to belong to a set of known nets. If not, log the new network and alert the user.
        if sourceMatch:
            checkknownnetwork(sourceIp, sourceMatch)
        if destMatch: 
            checkknownnetwork(destIp, destMatch)

        # If a host does not match an RFC1918 address or a user specified internal address that an internal address is talking to, note the external host and the internal host permitted to talk to it and notify the user about the permitted connection.
        if not sourceMatch and destMatch:
            global udpNetworkEgressPermitted
            if udpNetworkEgressPermitted == 0:
                prebellicoLog("-=-Egress Recon-=-\nNetwork egress detected! Internal hosts are permitted to connect to the internet via UDP.")
                udpNetworkEgressPermitted = 1
            knownExternalHost = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "externalHost" and data=(?)', sourceIp)
            if knownExternalHost is None:
                prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterface) values ("externalHost", ?, ?, "passiveNetwork", ?, ? )', [ sourceIp, destIp, timeStamp(), dev] )
                prebellicoLog(("-=-Egress Recon Update-=-\n%s is permitted to connect to %s on UDP port %s.") % (destIp, sourceIp, udpSourcePort))
                
        # If the UDP source port is less than or equal to 8000 and this is a host that does not exist in the HostIntelligence table, log the data and alert the user.
        hostExists = prebellicoDb('readFromDb', 'select * from HostIntelligence where ipAddress=(?)', sourceIp)
        if hostExists is None and udpSourcePort <= 8000:
            prebellicoLog(("-=-Host Recon-=-\nA new host was identified with an open UDP port: %s:%s") % (sourceIp, udpSourcePort))
            prebellicoDb('writeToDb', 'insert into HostIntelligence (firstObserved, lastObserved, ipAddress, macAddy, openUdpPorts, trustRelationships, discoveryInterface, interfaceIp) values (?,?,?,?,?,?,?,?)', [ timeStamp(), timeStamp(), sourceIp, sourceMac, udpSourcePort, destIp, dev, devip ] )

        # If this is a previous host and the port is less than 8000 (which is just an arbitary number - have to start somewhere), update the ports for the host.
        if hostExists is not None and udpSourcePort <=8000:
            # Using the source IP address, lookup open UDP ports to see if they match the source port captured within the packet. If this is a new port for this host, update the database and alert the user.
            getKnownUdpPorts = prebellicoDb('readFromDb', 'select openUdpPorts from HostIntelligence where ipAddress=(?)', sourceIp)
            if getKnownUdpPorts is not None:
                newUdpPorts = checkUnique(getKnownUdpPorts, udpSourcePort, 'int')
                if newUdpPorts != 0:
                    prebellicoDb('writeToDb', 'update HostIntelligence set openUdpPorts=(?), lastObserved=(?) where ipAddress = (?)', [ newUdpPorts, timeStamp(), sourceIp] )
                    prebellicoLog(("-=-Host Recon Update-=-\nA new open UDP port was discovered for %s. This host has the following open UDP ports: %s") % (sourceIp, newUdpPorts))

        # If we see someone scanning for SNMP using community strings, alert the user to the names that are used, and the source host that it is coming from. Typically this is a an IT/Security event, so this is attributed to 'Skynet'
        if udpDestPort == 161:
            snmpPacketFilterRegex = re.compile('[a-zA-Z0-9.*].*')# Regex to yank data within snmp string data
            snmpTempData=snmpPacketFilterRegex.findall(tempData)
            potentialSnmpStrings = re.split('[\x00-\x1f,\x7f-\xff]',snmpTempData[0])
            for justTheString in potentialSnmpStrings:
                if len(justTheString) >= 4:
                    communityString = justTheString
                    knownSnmpString = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "observedSnmp" and data=(?)', communityString)
                    knownSkynetSystem = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "skynet" and data=(?)', sourceIp)
                    if knownSkynetSystem is None:
                        prebellicoLog(("-=-Skynet Recon-=-\nA new security system has been identified: %s.") % ( sourceIp ))
                        prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterface) values ("skynet", ?, ?, "passiveNetwork", ?, ?)', [ sourceIp, sourceIp, timeStamp(), dev ] )
                    if knownSnmpString is None:
                        prebellicoLog(("-=-Skynet Recon-=-\n%s is scanning for systems with an SNMPv1 community string: %s") % ( sourceIp, communityString ))
                        prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterface) values ("observedSnmp",?,?,"passiveNetwork",?,?)', [ communityString, sourceIp, timeStamp(), dev ] )


	# If we have a response from a host on port 161, notify the user and extract the SNMP string - note this is buggy as there is not SNMP packet verification
	if udpSourcePort == 161:
		snmpPacketFilterRegex = re.compile('[a-zA-Z0-9.*].*(?=:)')# Regex to yank data before colon within snmp string data
		snmpTempData=snmpPacketFilterRegex.findall(tempData)
                potentialSnmpStrings = re.split('[\x00-\x1f,\x7f-\xff]',snmpTempData[0])
                for justTheString in potentialSnmpStrings:
                    if len(justTheString) >= 4:
                        communityString = justTheString
                
                # Look in the NetworkIntel table of the DB and see if we have observed this SNMP community string with a host before.
		knownValidatedSnmpString = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "validatedSnmp" and data=(?)', communityString)

                # If not, notify the user that this is a new string and store the data in the NetworkIntel table and HostIntel table.
                if knownValidatedSnmpString is None:
                    prebellicoLog(("-=-SNMP Recon-=-We have a new SNMPv1 community string from %s: %s") % ( sourceIp, communityString ))
                    prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterface) values ("validatedSnmp",?,?,"passiveNetwork",?,?)', [ communityString, sourceIp, timeStamp(), dev ] )
                    prebellicoDb('writeToDb', 'update HostIntelligence set validatedSnmp=(?), lastObserved=(?) where ipAddress = (?)', [communityString, timeStamp(), sourceIp] )

                # If this is not a new SNMP community string, work to verify if this string is unique to this host. I think this is rather inefficient.
                if knownValidatedSnmpString is not None:
                    hostsUsingValdiatedSnmpString = prebellicoDb('readFromDb', 'select associatedHost from NetworkIntelligence where recordType="validatedSnmp" and data=(?)', communityString)
                    
                    # This should never return as None, but there was a bug of some sorts where it did, so this is my quick fix after it pwned me.
                    if hostsUsingValdiatedSnmpString is not None:
                        countHostsUsingValidatedSnmpString = 0
                        notifyUserOfNewHostUsingSnmpString = 0 
                        while countHostsUsingValidatedSnmpString < len(hostsUsingValdiatedSnmpString):
                            if hostsUsingValdiatedSnmpString[countHostsUsingValidatedSnmpString] == sourceIp:
                                notifyUserOfNewHostUsingSnmpString = 1
                            countHostsUsingValidatedSnmpString += 1

                        # If this known SNMP community string is uniqe to this host, annotate it within the NetworkIntel table within the DB and notify the user.
                        if notifyUserOfNewHostUsingSnmpString == 0:
                            prebellicoLog(("-=-SNMP Recon-=-Identified another host that uses '%s' as an SNMP community string: %s") % ( communityString, sourceIp ))
                            prebellicoDb('writeToDb', 'update HostIntelligence set validatedSnmp=(?), lastObserved=(?) where ipAddress = (?)', [ communityString, timeStamp(), sourceIp ] )
                            prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterface) values ("validatedSnmp",?,?,"passiveNetwork",?,?)', [ communityString, sourceIp, timeStamp(), dev ] )

	# If we have an SMB packet, extract intelligence from this - this is going to be bigger than simply dumping the packets. Going to require classification of types of requests
	if udpSourcePort == 138:

            # Ran into a python bug that pwned me arse, so I rewrote this trying to solve the problem, which resulted in bloated code. I should work to trim this down.
            knownHostnameString = prebellicoDb('readFromDb', 'select hostname from HostIntelligence where ipAddress = (?)', sourceIp)
            knownHostDescriptionString = prebellicoDb('readFromDb', 'select hostDescription from HostIntelligence where ipAddress = (?)', sourceIp)
            mailSlotMatch = re.search("\\MAILSLOT.*BROWSE", ethernetPacket.child().child().child().get_buffer_as_string(), re.MULTILINE)
            if mailSlotMatch:
                mailSlotString = re.findall("(?<=\n\x00)(?!\x03\x90\x00)[\w\-\!\@\$\%\^\&\(\)\+\=\[\]\{\}\'\;\~\`]{1,15}(?=\x00)|(?<=\x0f\x01U\xaa)(?!\x03\x90\x00)[\w\s\:\-\=\_\-\+\[\]\{\}\!\@\#\$\%\^\&\*\(\)\'\"\:\;\~\`]+(?=\x00)", ethernetPacket.child().child().child().get_buffer_as_string(), re.MULTILINE)
                if len(mailSlotString) == 1:
                    if knownHostnameString[0] != mailSlotString[0]:
                        prebellicoLog(('-=-SMB Recon-=-\nThe hostname for \'%s\' is \'%s\'') % ( sourceIp, mailSlotString[0] ))
                        prebellicoDb('writeToDb', 'update HostIntelligence set hostname=(?), lastObserved=(?) where ipAddress = (?)', [ mailSlotString[0], timeStamp(), sourceIp ] )
                if len(mailSlotString) == 2:
                    if knownHostnameString[0] != mailSlotString[0] and knownHostDescriptionString != mailSlotString[1]:
                        prebellicoLog(('-=-SMB Recon-=-\nThe hostname for \'%s\' is \'%s\' and it describes itself as \'%s\'') % ( sourceIp, mailSlotString[0], mailSlotString[1] ))
                        prebellicoDb('writeToDb', 'update HostIntelligence set hostname=(?), hostDescription=(?), lastObserved=(?) where ipAddress = (?)', [ mailSlotString[0], mailSlotString[1], timeStamp(), sourceIp] )

	# Work support for HSRP protocol
	global hsrpNotification
	if ( udpSourcePort == 1985 and hsrpNotification != 1 ):
		prebellicoLog('-=-Layer2/3 Recon-=-\nCisco HSRP is spoken here')
                hsrpNotification = 1
        if ( udpSourcePort == 1985 ):
                hsrpTempData = ethernetPacket.child().child().child().get_buffer_as_string()
                hsrpPacketFilterRegex = re.compile('[a-zA-Z0-9.*].*')# Regex to yank data within snmp string data
                hsrpTempData=hsrpPacketFilterRegex.findall(hsrpTempData)
                
                #Trying to work past a bug here for various types of HSRP packets. To manage this I have adopted a try/except-pass method to manage these issues. Additionally, this doesn't really work to pull the hashed value, but manages a crash. Need to resolve this issue somehow.
                try: 
                    potentialHsrpPass = re.split('[\x00-\x1f,\x7f-\xff]',hsrpTempData[0])
                    for justTheString in potentialHsrpPass:
                        if len(justTheString) >= 4:
                            hsrpPass = justTheString
                            knownHsrpPassword = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "hsrp" and data=(?)', hsrpPass)
                            if len(hsrpPass) == 32:
                                md5Detect = re.match("(?:" + '[a-zA-Z0-9.*]{32}' + r")\Z", hsrpPass) # This is a re.findall hack for Python2.
                                if md5Detect is not None and knownHsrpPassword is None:
                                    prebellicoLog(('-=-Layer2/3 Recon-=-\nWe have an HSRP packet with either an MD5 hashed password or a raw password: %s') % ( hsrpPass ))
                                    prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterface) values ("hsrp",?,?,"passiveNetwork",?,?)', [ hsrpPass, sourceIp, timeStamp(), dev ] )
                            elif knownHsrpPassword is None: 
                                    prebellicoLog(('-=-Layer2/3 Recon-=-\nWe have an HSRP packet with an unhashed password: %s') % ( hsrpPass ))
                                    prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterfvace) values ("hsrp",?,?,"passiveNetwork",?,?)', [ hsrpPass, sourceIp, timeStamp(), dev ] )
                except:
                    pass
	return


# Function designed to sniff out intel tied to captured TCP PSH requests 
def tcppushdiscovery(header,data):

	# Start to decode the packet and determine the protocol number. If not TCP, return as it does not apply here.
	ethernetPacket = decoder.decode(data)
	protocolNumber = ethernetPacket.child().child().protocol
	if protocolNumber != 6:
		return 
	# Extract relevant data from the ethernet packet
	macHdr = ethernetPacket
        sourceMac = macHdr.as_eth_addr(macHdr.get_ether_shost())
        destMac = macHdr.as_eth_addr(macHdr.get_ether_dhost())
	ipHdr = ethernetPacket.child()
	tcpHdr = ipHdr.child()
        sourceIp = ipHdr.get_ip_src()
        sourcePort = tcpHdr.get_th_sport()
        destIp = ipHdr.get_ip_dst()
        destPort = tcpHdr.get_th_dport()

        # Pull TCP flags to determine tcp session state so that we can determine what TCP method to call for intel. 
	tcpSyn = ethernetPacket.child().child().get_SYN()
	tcpAck = ethernetPacket.child().child().get_ACK()
	tcpEce = ethernetPacket.child().child().get_ECE()
	tcpCwr = ethernetPacket.child().child().get_CWR()
	tcpFin = ethernetPacket.child().child().get_FIN()
	tcpPsh = ethernetPacket.child().child().get_PSH()
	tcpRst = ethernetPacket.child().child().get_RST()
	tcpUrg = ethernetPacket.child().child().get_URG()

        # If a TCP push packet is discovered from a previously unknown session, work to process it
        if ( tcpPsh == 1 and tcpAck == 1 ):
            #portexists = 0

            # Work to determine if these are known internal IP addresses based upon RFC1918 or user supplied data.
            (sourceMatch, destMatch) = ( checkinternaladdress(sourceIp), checkinternaladdress(destIp) )

            # Look to see if the IP address appears to belong to a set of known nets. If not, log the new network and alert the user.
            if sourceMatch:
                checkknownnetwork(sourceIp, sourceMatch)
            if destMatch:
                checkknownnetwork(destIp, destMatch)

            # If a host does not match an RFC1918 address or a user specified internal address that an internal address is talking to, note the external host and the internal host permitted to talk to it and notify the user about the permitted connection.
            if not sourceMatch and destMatch:
                global tcpNetworkEgressPermitted
                if tcpNetworkEgressPermitted == 0:
                    prebellicoLog("-=-Egress Recon-=-\nNetwork egress detected! Internal hosts are permitted to connect to the internet via TCP.")
                    tcpNetworkEgressPermitted = 1
                knownExternalHost = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "externalHost" and data=(?)', sourceIp)
                if knownExternalHost is None:
                    prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterface) values ("externalHost", ?,?,"passiveNetwork",?,?)', [ sourceIp, destIp, timeStamp(), dev ] )
                    prebellicoLog(("-=-Egress Recon Update-=-\n%s is permitted to connect to %s on TCP port %s.") % (destIp, sourceIp, sourcePort))

            # If completely arbitrary numbers based off of assumed sessions exist where the source port is less than 1024, extract intel and alert the user.
            if ( sourcePort <= 1024 and destPort > 1024 ):

                # If the host does not exist in the HostIntelligence table, log the data and alert the user.
                hostExists = prebellicoDb('readFromDb', 'select * from HostIntelligence where ipAddress=(?)', sourceIp)
                knownExternalHost = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "externalHost" and data=(?)', sourceIp)
                if hostExists is None and knownExternalHost is None:
                    prebellicoLog(("-=-TCP Push discovery-=-\nA new host was discovered with what appears to be an open TCP port - %s:%s. %s is talking to this service.") % ( sourceIp, sourcePort, destIp ))
                    prebellicoDb('writeToDb', 'insert into HostIntelligence (firstObserved, lastObserved, ipAddress, macAddy, openTcpPorts, trustRelationships, discoveryInterface, interfaceIp) values (?,?,?,?,?,?,?,?)', [ timeStamp(), timeStamp(), sourceIp, sourceMac, sourcePort, destIp, dev, devip ] )
                return

                # Using the source IP address, lookup open TCP ports to see if they match the source port captured within the packet. If this is a new port for this host, update the database and alert the user.
                getKnownTcpPorts = prebellicoDb('readFromDb', 'select openTcpPorts from HostIntelligence where ipAddress=(?)', sourceIp)
                if getKnownTcpPorts is not None:
                    newTcpPorts = checkUnique(getKnownTcpPorts, sourcePort, 'int')
                    if newTcpPorts != 0:
                        prebellicoDb('writeToDb', 'update HostIntelligence set openTcpPorts=(?), lastObserved=(?) where ipAddress = (?)', [ newTcpPorts, timeStamp(), sourceIp ] )
                        prebellicoLog(("-=-TCP Push discovery-=-\nThere appears to be an open TCP port on %s:%s, which is talking to %s.") % ( sourceIp, sourcePort, destIp ))
                # Using the source IP address, look up known trusted hosts and see if this is a new trusted host. If it is, log this and alert the user.
                getKnownTrustedHosts = prebellicoDb('readFromDb', 'select trustRelationships from HostIntelligence where ipAddress = (?)', sourceIp)
                if getKnownTrustedHosts is None:
                    prebellicoDb('writeToDb', 'update HostIntelligence set trustRelationships = (?), lastObserved = (?) where ipAddress = (?)', [ destIp, timeStamp(), sourceIp] )
                    prebellicoLog(("-=-Trust Intelligence-=-\nThe following host(s) are permitted to talk to %s: %s") % (sourceIp, destIp))
                elif getKnownTrustedHosts is not None:
                    newTrustedHosts = checkUnique(getKnownTrustedHosts, destIp, 'string')
                    if newTrustedHosts != 0:
                        prebellicoLog(("-=-Trust Intelligence-=-\nThe following host(s) are permitted to talk to %s: %s") % (sourceIp, newTrustedHosts))
                        prebellicoDb('writeToDb', 'update HostIntelligence set trustRelationships = (?), lastObserved = (?) where ipAddress = (?)', [ newTrustedHosts, timeStamp(), sourceIp ] )

                return

            # If the inverse of a session using TCP ports less than 1024 exist, extract intel and alert the user.
            if ( sourcePort > 1024 and destPort <= 1024 ):
                        # If the host does not exist in the HostIntelligence table, log the data and alert the user.
                hostExists = prebellicoDb('readFromDb', 'select * from HostIntelligence where ipAddress=(?)', destIp)
                knownExternalHost = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "externalHost" and data=(?)', destIp)
                if hostExists is None and knownExternalHost is None:
                    prebellicoLog(("-=-TCP Push discovery-=-\n%s appears to be talking to a newly discovered host on an open TCP port - %s:%s.") % ( sourceIp, destIp, destPort ))
                    prebellicoDb('writeToDb', 'insert into HostIntelligence (firstObserved, lastObserved, ipAddress, macAddy, discoveryInterface, interfaceIp) values (?,?,?,?,?,?)', [ timeStamp(), timeStamp(), destIp, destMac, dev, devip] )
                return

                # Using the source IP address, lookup open TCP ports to see if they match the source port captured within the packet. If this is a new port for this host, update the database and alert the user.
                getKnownTcpPorts = prebellicoDb('readFromDb', 'select openTcpPorts from HostIntelligence where ipAddress=(?)', destIp)
                if getKnownTcpPorts is not None:
                    newTcpPorts = checkUnique(getKnownTcpPorts, destPort, 'int')
                    if newTcpPorts != 0:
                        prebellicoDb('writeToDb', 'update HostIntelligence set openTcpPorts=(?), lastObserved=(?) where ipAddress = (?)', [ newTcpPorts, timeStamp(), destIp ] )
                        prebellicoLog(("-=-TCP Push discovery-=-\n%s appears to be talking to an open TCP port - %s:%s.") % ( sourceIp, destIp, destPort ))

                getKnownTrustedHosts = prebellicoDb('readFromDb', 'select trustRelationships from HostIntelligence where ipAddress = (?)', destIp)
                if getKnownTrustedHosts is None:
                    prebellicoDb('writeToDb', 'update HostIntelligence set trustRelationships = (?), lastObserved = (?)  where ipAddress = (?)', [ sourceIp, timeStamp(), destIp ] )
                    prebellicoLog(("-=-Trust Intelligence-=-\nThe following host(s) are permitted to talk to %s: %s") % (destIp, sourceIp))
                elif getKnownTrustedHosts is not None:
                    newTrustedHosts = checkUnique(getKnownTrustedHosts, sourceIp, 'string')
                    if newTrustedHosts != 0:
                        prebellicoLog(("-=-Trust Intelligence-=-\nThe following host(s) are permitted to talk to %s: %s") % (destIp, newTrustedHosts))
                        prebellicoDb('writeToDb', 'update HostIntelligence set trustRelationships = (?), lastObserved = (?) where ipAddress = (?)', [ newTrustedHosts, timeStamp(), destIp ] )
                return

            # If we have a situation where we are not sure where the server is, because both ports are above 1024, work to pool intel to determine where the server is.
            if ( sourcePort > 1024 and destPort > 1024 ):
                # If the host does not exist in the HostIntelligence table, log the data and alert the user.
                hostExists = prebellicoDb('readFromDb', 'select * from HostIntelligence where ipAddress=(?)', sourceIp)
                knownExternalHost = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "externalHost" and data=(?)', sourceIp)
                if hostExists is None and knownExternalHost is None:
                    prebellicoLog(("-=-TCP Push discovery-=-\nA new host was discovered %s, which is talking to %s:%s.") % ( sourceIp, destIp, destPort ))
                    prebellicoDb('writeToDb', 'insert into HostIntelligence (firstObserved, lastObserved, ipAddress, macAddy, discoveryInterface, interfaceIp) values (?,?,?,?,?,?)', [ timeStamp(), timeStamp(), sourceIp, sourceMac, dev, devip ] )

                # Using the source IP address, lookup open TCP ports to see if they match the source port captured within the packet. If this is a new port for this host, update the database and alert the user.
                getKnownTcpPorts = prebellicoDb('readFromDb', 'select openTcpPorts from HostIntelligence where ipAddress=(?)', sourceIp)
                if getKnownTcpPorts is not None:
                    newTcpPorts = checkUnique(getKnownTcpPorts, sourcePort, 'int')
                    if newTcpPorts != 0:
                        prebellicoLog(("-=-TCP Push discovery-=-\nThere appears to be a TCP based conversation between %s:%s and %s:%s. Consulting intelligence to see if we can identify which host has a listening TCP service.") % ( sourceIp, sourcePort, destIp, destPort ))
                
                        # Utilize the tcpPushSessionTracking data dictionary to pool intelligence about push sessions to find a common source port on a reoccuring host.
                        # If we have not stored this more than 10 times, add a new line to the database for the most recent event
                        countFullConnection = int(list(prebellicoDb('readFromDb', 'select count(sourceIp) from TcpPushSessionTracking where sourceIp = (?) and sourcePort = (?) and destIp = (?) and destPort = (?)', [ sourceIp, sourcePort, destIp, destPort ] ))[0])
                        if countFullConnection <= 11:
                            prebellicoDb('writeToDb', 'insert into TcpPushSessionTracking (sourceIp, sourcePort, destIp, destPort) values ((?),(?),(?),(?))', [ sourceIp, sourcePort, destIp, destPort] )

                        # Count the number of instances where the sourceIP and sourcePort are referenced in the database.
                        sourcePortCount = int(list(prebellicoDb('readFromDb', 'select count(sourceIp) from TcpPushSessionTracking where sourceIp = (?) and sourcePort = (?)', [ sourceIp, sourcePort ] ))[0])

                        # Count how many times the dest IP has connected to the sourceIp and sourcePort using a different port than destPort
                        destIpCount = int(list(prebellicoDb('readFromDb', 'select count(sourceIp) from TcpPushSessionTracking where sourceIp = (?) and sourcePort = (?) and destIp = (?) and destPort != (?)', [ sourceIp, sourcePort, destIp, destPort ] ))[0])

                        # Count how many times another host has connected to the sourceIP and sourcePort
                        nonDestIpCount = int(list(prebellicoDb('readFromDb', 'select count(sourceIp) from TcpPushSessionTracking where sourceIp = (?) and sourcePort = (?) and destIp != (?) and destPort != (?)', [ sourceIp, sourcePort, destIp, destPort ] ))[0])

                        # If the sourcePort appears to be associated with numerous other hosts on numerous other destPorts, report this to the user, store it in the HostIntelligence database, and clear the TcpPushSessionTracking database as this data will no longer be needed.
                        if sourcePortCount >= 3 and destIpCount >= 2 and nonDestIpCount >= 1:
                            prebellicoLog(("-=-TCP Push discovery-=-\nIntelligence confirms that %s is the server with open TCP port %s.") % ( sourceIp, sourcePort ))
                            prebellicoDb('writeToDb', 'update HostIntelligence set openTcpPorts=(?), lastObserved=(?) where ipAddress = (?)', [ newTcpPorts, timeStamp(), sourceIp ] )

                            # Determine if this is a widely used service, such as a network proxy. If so, alert the user and log the data to the NetworkIntel db.
                            numberOfServiceClients = int(list(prebellicoDb('readFromDb', 'select count (distinct destIp) from TcpPushSessionTracking where sourceIp = (?) and sourcePort = (?)', [ sourceIp, sourcePort ] ))[0])
                            if numberOfServiceClients >= 5:
                                prebellicoLog(("-=-TCP Push discovery-=-\nIntelligence confirms that %s:%s is a heavily used network service. While pooling data, %s clients where found to be interacting with this service.") % ( sourceIp, sourcePort, numberOfServiceClients ))
                                enterpriseService = str(sourceIp) + ":" + str(sourcePort)
                                prebellicoDb('writeToDb', 'insert into NetworkIntelligence set recordType = "enterpriseService", data = (?), associatedHost = (?), methodObtained = (?), dateObserved = (?), sourceInterface = (?)', [ enterpriseService, sourceIp, "passiveNetwork", timeStamp(), dev ] )
                                prebellicoDb('writeToDb', 'delete from TcpPushSessionTracking where sourceIP = (?) and sourcePort = (?)', [ sourceIp, sourcePort ] )
                return


# Function designed to sniff out intel tied to generic TCP intelligence such as predictable IPID numbers        
def tcpdiscovery(header,data):

	# Start to decode the packet and determine the protocol number. If not TCP, return as it does not apply here.
	ethernetPacket = decoder.decode(data)
	protocolNumber = ethernetPacket.child().child().protocol
	if protocolNumber != 6:
		return 
	# Extract relevant data from the ethernet packet
	macHdr = ethernetPacket
	ipHdr = ethernetPacket.child()
	tcpHdr = ipHdr.child()
	sourceIpSequenceNumber = tcpHdr.get_th_seq()
	sourceIp = ipHdr.get_ip_src()

        # Work to determine if we have an IPID sequence number from this host. If so, simply return for more carnage.
        checkKnownIpidNumberHost = prebellicoDb('readFromDb', 'select zombieIpid from HostIntelligence where ipAddress=(?)', sourceIp)
        if checkKnownIpidNumberHost is not None:
            return

	# Get a count of ipid sequence numbers
	ipidCount = len(tcpIpidNumbers[sourceIp])

	# Once we have three IPID sequence numbers, look for predictability and clean the list of ipid sequence numbers to preserve memory
        if ipidCount == 12:
		oldZombieHost = 0
		ipidItem = 0
		oldDiffIpid = 0
		diffIpidMatch = 0
		while ipidItem <= 10:
			newDiffIpid = tcpIpidNumbers[sourceIp][ipidItem] - tcpIpidNumbers[sourceIp][ipidItem + 1]
			if oldDiffIpid == newDiffIpid:
				diffIpidMatch += 1
				for zombieHost in zombieHosts.keys():
					if zombieHost == sourceIp:
						oldZombieHost = 1
			oldDiffIpid = newDiffIpid
			ipidItem += 1
		if ( oldZombieHost == 0 and diffIpidMatch >= 10 and newDiffIpid != 0 ):
                        prebellicoDb('writeToDb', 'update HostIntelligence set zombieIpid=(?), lastObserved=(?) where ipAddress = (?)', [newDiffIpid, timeStamp(), sourceIp] )
			prebellicoLog(("-=-Zombie Recon-=-\n%s uses predictible IPID sequence numbers! Last difference:%s. Captured IPID sequence numbers:\n%s\n") % ( sourceIp,newDiffIpid,tcpIpidNumbers[sourceIp] ))
			for ipidNumber in tcpIpidNumbers[sourceIp]:
				zombieHosts[sourceIp].add(ipidNumber)
		# Clean the list of ipid sequence numbers to preserve memory
		ipidMaster = tcpIpidNumbers[sourceIp][11]
		del tcpIpidNumbers[sourceIp]
		tcpIpidNumbers[sourceIp].append(ipidMaster)
	if sourceIpSequenceNumber != 0:
		tcpIpidNumbers[sourceIp].append(sourceIpSequenceNumber)
	return


# Function designed to sniff out the TCP syn/ack portion of the three way handshake to enumerate listing services for a host
def synackdiscovery(header, data):

	# Start to decode the packet and determine the protocol number. If not TCP, return as it does not apply here.
        ethernetPacket = decoder.decode(data)
        protocolNumber = ethernetPacket.child().child().protocol
        if protocolNumber != 6:
                return
        # Extract relevant data from the ethernet packet
        macHdr = ethernetPacket
        sourceMac = macHdr.as_eth_addr(macHdr.get_ether_shost())
        destMac = macHdr.as_eth_addr(macHdr.get_ether_dhost())
        ipHdr = ethernetPacket.child()
        tcpHdr = ipHdr.child()
        sourceIp = ipHdr.get_ip_src()
        sourcePort = tcpHdr.get_th_sport()
        destIp = ipHdr.get_ip_dst()
        destPort = tcpHdr.get_th_dport()

        # Pull TCP flags to determine tcp session state so that we can determine what TCP method to call for intel. 
        tcpSyn = ethernetPacket.child().child().get_SYN()
        tcpAck = ethernetPacket.child().child().get_ACK()
        tcpEce = ethernetPacket.child().child().get_ECE()
        tcpCwr = ethernetPacket.child().child().get_CWR()
        tcpFin = ethernetPacket.child().child().get_FIN()
        tcpPsh = ethernetPacket.child().child().get_PSH()
        tcpRst = ethernetPacket.child().child().get_RST()
        tcpUrg = ethernetPacket.child().child().get_URG()

        # Work to determine if these are known internal IP addresses based upon RFC1918 or user supplied data.
        (sourceMatch, destMatch) = ( checkinternaladdress(sourceIp), checkinternaladdress(destIp) )

        # Look to see if the IP address appears to belong to a set of known nets. If not, log the new network and alert the user.
        if sourceMatch:
            checkknownnetwork(sourceIp, sourceMatch)
        if destMatch:
            checkknownnetwork(destIp, destMatch)

        # If a host does not match an RFC1918 address or a user specified internal address that an internal address is talking to, note the external host and the internal host permitted to talk to it and notify the user about the permitted connection.
        if not sourceMatch and destMatch:
            global tcpNetworkEgressPermitted
            if tcpNetworkEgressPermitted == 0:
                prebellicoLog("-=-Egress Recon-=-\nNetwork egress detected! Internal hosts are permitted to connect to the internet via TCP.")
                tcpNetworkEgressPermitted = 1
            knownExternalHost = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "externalHost" and data=(?)', sourceIp)
            if knownExternalHost is None:
                prebellicoDb('writeToDb', 'insert into NetworkIntelligence (recordType, data, associatedHost, methodObtained, dateObserved, sourceInterface) values ("externalHost", ?, ?, "passiveNetwork", ?, ?)', [ sourceIp, destIp, timeStamp(), dev ] )
                prebellicoLog(("-=-Egress Recon Update-=-\n%s is permitted to connect to %s on TCP port %s.") % (destIp, sourceIp, sourcePort))

        # If the host does not exist in the HostIntelligence table, log the data and alert the user.
        hostExists = prebellicoDb('readFromDb', 'select * from HostIntelligence where ipAddress=(?)', sourceIp)
        knownExternalHost = prebellicoDb('readFromDb', 'select * from NetworkIntelligence where recordType = "externalHost" and data=(?)', sourceIp)
        if hostExists is None and knownExternalHost is None:
            prebellicoLog(("-=-Host Recon-=-\nA new host was identified with an open TCP port: %s:%s") % (sourceIp, sourcePort))
            prebellicoDb('writeToDb', 'insert into HostIntelligence (firstObserved, lastObserved, ipAddress, macAddy, openTcpPorts, trustRelationships, discoveryInterface, interfaceIp) values (?,?,?,?,?,?,?,?)', [ timeStamp(), timeStamp(), sourceIp, sourceMac, sourcePort, destIp, dev, devip ] )
            return

        # Using the source IP address, lookup open TCP ports to see if they match the source port captured within the packet. If this is a new port for this host, update the database and alert the user.
        getKnownTcpPorts = prebellicoDb('readFromDb', 'select openTcpPorts from HostIntelligence where ipAddress=(?)', sourceIp)
        if getKnownTcpPorts is not None:
            newTcpPorts = checkUnique(getKnownTcpPorts, sourcePort, 'int')
            if newTcpPorts != 0:
                prebellicoDb('writeToDb', 'update HostIntelligence set openTcpPorts=(?), lastObserved=(?) where ipAddress = (?)', [ newTcpPorts, timeStamp(), sourceIp ] )
                prebellicoLog(("-=-Host Recon Update-=-\nA new open TCP port was discovered for %s. This host has the following open TCP ports: %s") % (sourceIp, newTcpPorts))

        getKnownTrustedHosts = prebellicoDb('readFromDb', 'select trustRelationships from HostIntelligence where ipAddress = (?)', sourceIp)
        if getKnownTrustedHosts is None:
            prebellicoDb('writeToDb', 'update HostIntelligence set trustRelationships = (?), lastObserved = (?) where ipAddress = (?)', [ destIp, timeStamp(), sourceIp ] )
            prebellicoLog(("-=-Trust Intelligence-=-\nThe following host(s) are permitted to talk to %s: %s") % (sourceIp, destIp))
        elif getKnownTrustedHosts is not None:
            newTrustedHosts = checkUnique(getKnownTrustedHosts, destIp, 'string')
            if newTrustedHosts != 0:
                prebellicoLog(("-=-Trust Intelligence-=-\nThe following host(s) are permitted to talk to %s: %s") % (sourceIp, newTrustedHosts))
                prebellicoDb('writeToDb', 'update HostIntelligence set trustRelationships = (?), lastObserved = (?) where ipAddress = (?)', [ newTrustedHosts, timeStamp(), sourceIp ] )
	return


# Function to deal with the shenanigans of how data is returned from and stored to the sqlite db. This basically takes the tuple returned from a single row/column in the DB and validates if something new has been discovered, and if so, returns an ordered string that can later be retrieved in the same manner.
def checkUnique(currentList, newValue, sortType):
    newValue = newValue
    countKnownValues = 0
    notifyUserOfNewValue = 0
    while countKnownValues < len(currentList):
        if currentList[countKnownValues] == newValue:
            notifyUserOfNewValue = 1
            countKnownValues += 1

        # If this really is a unique value add it to the list of values for additional checks.
        if notifyUserOfNewValue == 0:

            # I know what you are thinking. Why!?!? The stackoverflow gods hate me for this but after many hours of blood sweat and tears I finally got this POS funtion to work with what was once an easy task with data dictionaries, so there is your answer. 
            knownValues = list(currentList)
            knownValues.append(newValue)
            newValues = str(knownValues)
            newValues = newValues.strip('[')
            newValues = newValues.strip(']')
            newValues = newValues.replace(",", "")
            newValues = newValues.replace("'", "")
            newValues = newValues.replace("u", "")
            newValues = newValues.replace("None", "")
            tempValues = newValues.split(" ")
            countTempValues = len(tempValues)
            tempValues = list(set(tempValues))
            #if sortType == 'int':
            #    tempValues.sort(key=int)
            #else:
            #    tempValues.sort
            tempValues.sort
            countSortedTempValues = len(tempValues)
            newValues = str(tempValues)
            newValues = newValues.strip('[')
            newValues = newValues.strip(']')
            newValues = newValues.replace(",", "")
            newValues = newValues.replace("'", "")
            newValues = newValues.replace("u", "")
            newValues = newValues.replace("None", "")

            # If something truly has changed, store this in a temp var and pass it to the user, otherwise, return a 0.
            if countTempValues == countSortedTempValues:
                sortedString = newValues
            else:
                sortedString = 0
            return(sortedString)


# Function to get an interface from the user, should one not have been provided by the user.
def getInterface():
    # Grab a list of interfaces that pcap is able to listen on. If only one interface exists, roll with that, otherwise prompt the user to select an interface.
    print '\nSearching the system for compatible devices.'
    ifs = findalldevs()

    # No interfaces available, abort.
    if 0 == len(ifs):
        print "\nYou don't have enough permissions to open any interface on this system."
        sys.exit(1)

    # Only one interface available, use it.
    elif 1 == len(ifs):
        print "\nOnly one interface present, defaulting to it."
        return ifs[0]

    # Ask the user to choose an interface from the list.
    else:
        print "\nNumerous compatible interfaces identified:\n"
        count = 0
        for iface in ifs:
            try:
                t=open_live(iface, 1500, 0, 100)
                if( t.getnet() != '0.0.0.0' and t.datalink() ==  pcapy.DLT_EN10MB ):
                    print '%i - %s' % (count, iface)
                    count += 1
            except PcapError, e:
                break
    idx = int(raw_input("\nPlease select an interface you would like to use:"))
    return ifs[idx]


# Function to gather interface information and set the interface in sniffing mode if an interface is provided or selected during runtime.
def sniffInterface(dev):
    # Obtain the selected interface IP to use as a filter, allowing us to pwn all the things without pissing in prebellico's data pool
    devip = netifaces.ifaddresses(dev)[2][0]['addr']

    # Place the ethernet interface in promiscuous mode, capturing one packet at a time with a snaplen of 1500
    print("\nPlacing the '%s' interface in sniffing mode.") % ( dev )
    sniff = pcapy.open_live(dev, 1500, 1, 100)
    print "\nListening on %s: IP = %s, net=%s, mask=%s, linktype=%d" % (dev, devip, sniff.getnet(), sniff.getmask(), sniff.datalink())
    time.sleep(1)
    return(devip, sniff)


# Function to read from a pcap file if an interface is not defined and a PCAP file is provided to read from
# Note that the PCAP frame size has to be 262144 or lower by design per https://github.com/the-tcpdump-group/libpcap/commit/f983e075fbef40fe12323c4dd8f85c88eaf0f789 
def sniffFile(pcapFile):    
    print("\nOpening the %s PCAP file for processing.") % ( pcapFile )
    sniff=pcapy.open_offline( pcapFile )
    time.sleep(1)
    return(sniff)


# Function to track wait time between intel should the user set this as a preference.
def checkPrebellicoWaitTimer():
    global currentWaitTime
    prebellicoReconPhaseShift = 0
    currentTime = time.time()
    currentWaitTime = round(((currentWaitTime-currentTime)/60)/60) 
    if ( updateWaitTime - int(currentWaitTime)) == 1:
        prebellicoLog("-=-Prebellico Event Montior-=-\nWARNING: It has been some time since prebellico logged an update from the network. In one hour Prebellico will shift from a 100% passive state.")
    elif currentWaitTime == trackUpdateTime:
        prebellicoLog("-=-Prebellico Event Monitor-=-\nIt has been %s hours since the last update. Shifting to a more agressive form of reconnissiance") % ( int(currentWaitTime) )
        prebellicoReconPhaseShift = 1
    return(prebellicoReconPhaseShift)

###
### Prebellico variables and data dictionarires used throughout the application.
###

# Define a data dictionary for TCP IPID squence numbers to look for zombie hosts
tcpIpidNumbers = defaultdict(list)

# Define a data dictionary for zombie hosts
zombieHosts = defaultdict(set)

# Define global vars for tracking notification of network egress.
tcpNetworkEgressPermitted = 0
udpNetworkEgressPermitted = 0
icmpNetworkEgressPermitted = 0
tcpNetworkEgressPermitted = 0

# Define a variable to control output of HSRP traffic - This is temporary until this is more built out.
hsrpNotification = 0

# Parse arguments from user via argparse
parser = argparse.ArgumentParser()
parser.add_argument('-i', '--inf', help='Specify the interface you want Prebellico to listen on. By default Prebellico will hunt for interfaces and ask the user to specify an interface if one is not provided here.')
parser.add_argument('-r', '--read', help='Specify a PCAP file to read from instead of a network interface. By default Prebellico assumes that traffic is to be read from a network interface.')
parser.add_argument('-l', '--log', help='Specify an output file. By default Prebellico will log to "prebellico.out" if a logfile is not specified.')
parser.add_argument('-d', '--db', help='Specify an sqlite db file you want to write to. By default this will create, if need be, and write to "prebellico.db" if not specified by the user, as long as the file is an actual Prebellico DB that the user can read from.')
parser.add_argument('-e', '--extra', help='Specify extra filtering using PCAP based syntax. By default, "ip or arp or aarp and not host 0.0.0.0 and not host <interface_IP>" is used as a filter.')
parser.add_argument('-t', '--targets', help='Specify targets of interest.')
parser.add_argument('-w', '--wait', type=int, help='Specify a period of time in hours to wait for new intelligence before shifting to a new form of intelligence gathering.')
parser.add_argument('-s', '--subsume', help='Include traffic from the target interface from Prebellico output. By default this traffic is excluded to ensure data generated by the interface while interacting with the environment does not taint the "fingerprint" of the target environment.', action='store_true')
parser.add_argument('-p', '--semipassive', help='Perform semi-passive data collection after a specified period of time where no new passive intelligence is aquired.', action='store_true')
parser.add_argument('-a', '--semiaggressive', help='Perform semi-aggressive data collection after a specififed period of time where no new passive or semi-passive intelligence is aquired.', action='store_true')
parser.add_argument('-f', '--fireforeffect', help='After semipassive and semiaggressive attacks are complete, get aggressive by reading from a specified file and execute commands within that file against the provided targets.')
parser.add_argument('-g', '--greenlightdate', help='The specific date to execute commands within the "fireforeffect" file against the target list. This will require the defined wait period to pass, a list of targets, as well as all semipassive and semiagressive attacks to complete before these are carried out.')
parser.add_argument('-q', '--quiet', help='Remove the Prebellico banner at the start of the script.', action='store_true')

args = vars(parser.parse_args())

# Call the prebellico banner if the user has not disabled this function
showBanner=args['quiet']
if showBanner is False:
    prebellicoBanner()

# Check the prebellico database
checkPrebellicoDb()

# Setting logging parameters
logfile=args['log']
if logfile is None:
    logging.basicConfig(filename='prebellico.log', format='%(message)s', level=logging.INFO)
else:
    logging.basicConfig(filename=logfile, format='%(message)s', level=logging.INFO)
console = logging.StreamHandler()
logging.getLogger('').addHandler(console)

# Determine if a device or file has been specififed. If the user requested to listen from a file instead of a network interface, ensure that both are not used. If a device or file has not been specified, hunt for compatible devices and ask the user to select a compatible device - Note, this is a bit of a hack, but it works.
dev=args['inf']
readPcapFile=args['read']
if readPcapFile is not None and dev is not None:
    print("\nReading from both a PCAP file and sniffing from an interface at the same time is not permitted. Consider processing the PCAP before or after sniffing from a live interface, refrencing the same Prebellico database.")
    exit()
if readPcapFile is not None and dev is None:
    # Set dummy interfaces and IP's for logging purposes
    dev=readPcapFile
    devip=readPcapFile
    # Read from the PCAP file and process it.
    sniff = sniffFile(readPcapFile)
if readPcapFile is None and dev is None:
    print("\nAn interface or a PCAP file was not provided.")
    dev = getInterface()
if readPcapFile is None and dev is not None:
    ( devip, sniff) = sniffInterface(dev)

# Set a filter for data based upon user preferences.
includeInterface=args['subsume']
extraPcapSyntax=args['extra']
filter = ("ip or arp or aarp and not host 0.0.0.0")
if includeInterface is False and readPcapFile is None:
    filter = filter + (" and not host %s") % ( devip )
if extraPcapSyntax is not None:
    filter = filter + (" %s") % ( extraPcapSyntax.lstrip() )
print("\nSetting filter syntax: %s.") % ( filter )
try:
    sniff.setfilter(filter)
except PcapError, e:
    print("\nSomething is wrong with your PCAP filter syntax: %s") % (e)
    print("\nPlease correct these issues and try again.")
    exit()

# If the user has set a timer to shift into another form of agressive reconnissiance, generate a timer timestamp to use as a baseline.
trackUpdateTime = args['wait']
if trackUpdateTime is not None:
    initialReconUpdateTimeCheck = 0 # Used for initial setup with the inspectproto updateReconCheckTimer function.
    updateWaitTime = trackUpdateTime
    prebellicoLog(("-=-Prebellico Event Monitor-=-\nSetting update timer to %s hours.") % ( trackUpdateTime))
    currentWaitTime = time.time()

# Start the impact packet decoder
print("\nWatching for relevant intelligence.\n")
decoder = ImpactDecoder.EthDecoder()
time.sleep(1)

# Call the inspectproto function to determine protocol support
sniff.loop(0, inspectproto)

