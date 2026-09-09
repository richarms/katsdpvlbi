# jive5ab multicast isolation

`jive5ab-multicast-isolation.patch` applies to the Dockerfile's pinned revision
`b228209b4fa4e1f4a61b76b89974935fa6d27836`.

On Linux, the receiver joins each multicast group on its own wildcard-bound
socket. The default `IP_MULTICAST_ALL=1` delivers traffic from all groups joined
on the host to each socket sharing the UDP port. Independent UDPs sequence
numbers then collide. A four-group lab fixture reproduced a recording containing
four copies of the final VDIF thread instead of the four distinct threads.

The patch sets `IP_MULTICAST_ALL=0` for multicast receiver sockets when the socket
option is available. Setting it must succeed. This keeps reception limited to
groups joined by that socket. The change needs to be submitted upstream; it is
carried here so the pinned recorder build can be tested with four same-port groups.

This patch was written locally during the 9 September 2026 lab test, rather than
taken from an upstream fix. Repeating the three-second, four-group UDPs fixture
with the patch recorded 38,400 frames: 9,600 per VDIF thread, with no duplicates
or invalid headers. Controller-driven closure and vlbimeta pass-through
publication completed on the recorder host. This test used a sender on that
same host; it does not establish cross-host delivery or real CBF compatibility.
