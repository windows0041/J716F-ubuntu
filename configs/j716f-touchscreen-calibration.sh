#!/bin/sh
# Reapply the verified J716F touchscreen transform after GNOME initializes XInput.

matrix='1 0 0 0 1 0 0 0 1'
sleep 5
attempt=0
while [ "$attempt" -lt 15 ]; do
    id=$(/usr/bin/xinput list --id-only 'pointer:Goodix Capacitive TouchScreen' 2>/dev/null)
    if [ -n "$id" ]; then
        /usr/bin/xinput set-prop "$id" "Coordinate Transformation Matrix" $matrix
        exit $?
    fi
    attempt=$((attempt + 1))
    sleep 1
done
exit 1
