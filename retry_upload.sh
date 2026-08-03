#!/bin/bash
set -u
IP=$(printf '%d.%d.%d.%d' 192 168 23 66)
SSH="ssh -o ConnectTimeout=8 -o BatchMode=yes -o StrictHostKeyChecking=accept-new tashan@${IP}"
$SSH "python3 ~/.zmax/upload_data_v2.py $1" 2>&1
