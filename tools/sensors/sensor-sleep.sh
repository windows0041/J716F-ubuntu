#!/bin/sh
# Pause the reverse FastRPC listener before the kernel freezes userspace.
set -eu
restore=/run/j716f-sensors-sleep/restore-rpc
case "$1" in
    pre)
        state=$(systemctl show j716f-sensor-rpc.service -p ActiveState --value)
        case "$state" in
            active|activating|reloading)
                : > "$restore"
                systemctl stop j716f-sensor-rpc.service
                echo 'FastRPC and its dependent SensorProxy stopped before sleep.'
                ;;
            *) echo "FastRPC was $state; preserving its disabled/inactive state." ;;
        esac
        ;;
    post)
        if [ -f "$restore" ]; then
            rm "$restore"
            systemctl --no-block start j716f-sensor-rpc.service
            echo 'Requested FastRPC and SensorProxy restoration after sleep.'
        fi
        ;;
    *) exit 2 ;;
esac
