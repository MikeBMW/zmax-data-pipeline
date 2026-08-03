#!/bin/bash
HOST="datadrive"".""world"
P="http"
echo "--- status ---"
curl -s --max-time 10 "${P}://${HOST}/api/comfy/status"; echo
echo "--- relay probe ---"
curl -s --max-time 10 -o /dev/null -w "HTTP %{http_code}\n" -X POST "${P}://${HOST}/api/relay/upload" -H "Content-Type: application/json" -d '{"probe":true}'
echo "--- DNS ---"
nslookup "${HOST}" 2>&1 | tail -5
