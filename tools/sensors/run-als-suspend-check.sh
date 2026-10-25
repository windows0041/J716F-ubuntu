#!/bin/sh
# Execute only after the user confirms saved work and readiness to wake the tablet.
set -eu
umask 077
test "$(id -u)" = 0
test "$(uname -r)" = 6.15.11
test "$(cat /sys/bus/i2c/devices/4-0061/power/wakeup)" = enabled
test -z "$(cat /sys/class/rtc/rtc0/wakealarm)"
als_label=${1:-1}
case "$als_label" in 1|2|3) ;; *) exit 2 ;; esac
als_trial=/var/lib/j716f-sensors/stability-20261023/suspend-$als_label
mkdir -m 0700 "$als_trial"
exec > "$als_trial/trial.log" 2>&1
als_before=$(cat /sys/power/suspend_stats/success)
als_armed=0
als_alarm=
cleanup() {
    if [ "$als_armed" = 1 ] && [ "$(cat /sys/class/rtc/rtc0/wakealarm)" = "$als_alarm" ]; then
        printf '0\n' > /sys/class/rtc/rtc0/wakealarm
    fi
}
trap cleanup EXIT HUP INT TERM
date -Is
echo "SUSPEND_SUCCESS_BEFORE=$als_before"
cat /proc/sys/kernel/random/boot_id
systemctl show j716f-sensor-rpc.service iio-sensor-proxy.service -p Id -p ActiveState -p NRestarts
dmesg > "$als_trial/kernel.before.log"
rtcwake -d /dev/rtc0 -m no -s 45
als_alarm=$(cat /sys/class/rtc/rtc0/wakealarm)
als_armed=1
echo 'SUSPENDING: RTC fallback is armed for 45 seconds.'
systemctl suspend
als_count=0
while [ "$(cat /sys/power/suspend_stats/success)" -le "$als_before" ]; do
    als_count=$((als_count + 1))
    if [ "$als_count" -ge 60 ]; then echo 'No completed suspend within the bounded window'; exit 1; fi
    sleep 1
done
echo RESUMED
date -Is
cat /sys/power/suspend_stats/success
systemctl show j716f-sensor-rpc.service iio-sensor-proxy.service -p Id -p ActiveState -p Result -p NRestarts
# Only read properties; GNOME remains the sole light-sensor claimant.
python3 -u - "$als_trial/values.jsonl" <<'PY'
import json, subprocess, sys, time
from pathlib import Path
deadline = time.monotonic() + 100
with open(sys.argv[1], 'w', buffering=1) as log:
    while time.monotonic() < deadline:
        try:
            r = subprocess.run(['busctl', '--system', 'get-property',
                'net.hadess.SensorProxy', '/net/hadess/SensorProxy',
                'net.hadess.SensorProxy', 'LightLevel'],
                capture_output=True, text=True, timeout=3)
            light = r.stdout.strip() or r.stderr.strip()
        except subprocess.TimeoutExpired:
            light = 'timeout'
        log.write(json.dumps(dict(monotonic=time.monotonic(), light=light,
            brightness=Path('/sys/class/backlight/ae94000.dsi.0/brightness').read_text().strip()))+'\n')
        time.sleep(1)
PY
dmesg > "$als_trial/kernel.after.log"
systemctl show j716f-sensor-rpc.service iio-sensor-proxy.service -p Id -p ActiveState -p Result -p NRestarts
echo TRIAL_COMPLETE
