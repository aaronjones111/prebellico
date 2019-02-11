# prebellico
100% Passive Network Reconnaissance Tool

## Challenge your assumptions
When attacking, auditing or defending modern internal networks, intelligence is everything.  Understanding the environment can be the difference between successfully penetrating or defending the target environment.

Over the years, internal audit and testing engagements have been operating on various assumptions within switched networks, often driving engagement execution methods. 

But what if these assumptions were wrong? 

What if we could utilize the idle time, the days or even weeks in advance between deployment and engagement execution, the off-hour pauses, to understand the network and reclaim wasted time? As attackers, what if we could leverage the realities of modern networks and the things customers do to ‘prepare’ for an engagement (backups, security scans, etc.) through 100% passive methods? What if you could gain a foothold into an organization prior to engagement through just listening?

Obtaining information about the network in a stealthy manner can be difficult within a mature environment. Even during overt engagements, obtaining the information you need within a limited time window can be difficult. There are engagement delays, there are poor descriptions, there are poor assumptions, there are simulated or test environments. 

These things can easily lead to unrealistic scope reductions a real-world attacker would not operate out of. 

## Who this is for
Prebellico is great for red teams, blue teams, penetration testers, auditors, defenders and hunters alike; anyone who wants to know more about the network they're in. 

It is a 100% passive network reconnaissance tool designed to challenge assumptions made about the target environment that may have arisen around the intent of the engagement. 

Prebellico fingerprints the environment without touching it, gathering information about the target environment prior to, and during, an engagement without transmission, including what is called reverse port scanning. 

## Operation
### Active 
Deployment and execution is simple.  Simply launch Prebellico as a root user, select the listening interface, and the information it gathers will be:
- dumped to the screen
- logged to a file
- recorded to a database file (SQLite)

Prebellico has built in query options to explore acquired db information, and the log file matches screen output verbatum.

By design Prebellico operates in a 100% passive state while ignoring traffic generated by the localhost and uses very few resources. Concequently, there is no need to be concerned about it impacting an environment or overusing resources, regardless of the engagement timeline or objective.

### Pre engagement / post-mortem
Want to further understand an environment you don’t yet have access to? 

Want to know how to better scope your engagement prior to execution?

Want to understand the environment your tending?

Prebellico has the ability to process PCAP files (with a maximum SNAPLEN of 262144 bytes) prior, during, or after an engagement. This is useful for things like processing historical data obtained elsewhere or for scope validation purposes prior to engagement kickoff. You can also merge this data during the engagement by copying the database over and specifying the database and log file at launch time, if so desired.

Prebellico - Because there is no patch for 100% passive reconnaissance.
