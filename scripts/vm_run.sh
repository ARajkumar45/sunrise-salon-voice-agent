#!/bin/sh
# Run a long command on the VM detached from the SSH session, so a dropped connection
# (for example on a train) cannot kill it. Usage: scripts/vm_run.sh <name> '<command>'
# Output goes to /tmp/<name>.log on the VM; /tmp/<name>.done appears when it finishes.
name=$1; shift
ssh -o ConnectTimeout=20 porsai "cd ~/app && rm -f /tmp/$name.done && nohup sh -c '$* > /tmp/$name.log 2>&1; touch /tmp/$name.done' >/dev/null 2>&1 &"
