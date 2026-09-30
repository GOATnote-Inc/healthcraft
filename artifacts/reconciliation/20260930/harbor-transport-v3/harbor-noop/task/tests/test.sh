#!/bin/sh
set -eu
printf "0\n" > /logs/verifier/reward.txt
python /usr/local/bin/hc-ehr.py tools > /logs/verifier/tools.json
printf "1\n" > /logs/verifier/reward.txt
