#!/bin/sh
# openAMDC container entrypoint.
# With no arguments the image baseline config is used; otherwise all
# arguments are passed through to openamdc-server unchanged.
set -e

if [ "$#" -eq 0 ]; then
    set -- /etc/openamdc/openamdc.conf
fi

exec openamdc-server "$@"
