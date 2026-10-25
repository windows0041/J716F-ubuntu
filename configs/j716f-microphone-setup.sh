#!/bin/sh
# J716F / Linux #522: reproduce the capture path verified on 2026-10-22.
# The board's selector is PM8150B GPIO1 (line offset 0), active high.
# This helper never relies on a global GPIO number or fixed gpiochip index.
set -eu

fail() { echo "J716F microphone: $*" >&2; exit 1; }

tr '\000' '\n' </proc/device-tree/compatible |
    grep -qx 'lenovo,j716f' || fail 'unexpected board'

find_chip() {
    found=''
    for node in /sys/bus/gpio/devices/gpiochip*; do
        [ -e "$node/of_node" ] || continue
        case "$(readlink -f "$node/of_node")" in
            */pmic@2/gpio@c000)
                tr '\000' '\n' <"$node/of_node/compatible" |
                    grep -qx 'qcom,pm8150b-gpio' || fail 'unexpected PMIC GPIO compatible'
                [ -z "$found" ] || fail 'ambiguous PM8150B GPIO controller'
                found=${node##*/}
                ;;
        esac
    done
    [ -n "$found" ] || return 1
    gpioinfo "$found" | head -n 1 | grep -q ' - 12 lines:' ||
        fail 'unexpected GPIO controller size'
    echo "$found"
}

wait_chip() {
    attempts=0
    while ! chip=$(find_chip); do
        attempts=$((attempts + 1))
        [ "$attempts" -lt 40 ] || fail 'PM8150B GPIO controller unavailable'
        sleep 0.5
    done
}

set_control() {
    amixer -c L2021 cset "name=$1" "$2" >/dev/null
    actual=$(amixer -c L2021 cget "name=$1" |
        sed -n 's/^[[:space:]]*: values=//p')
    [ "$actual" = "$3" ] || fail "control readback failed: $1 ($actual)"
}

case "${1:-}" in
    selector)
        wait_chip
        echo "J716F microphone: holding $chip line 0 high (PM8150B GPIO1)"
        exec gpioset --mode=signal "$chip" 0=1
        ;;
    routes)
        wait_chip
        attempts=0
        while ! gpioinfo "$chip" |
            grep -Eq 'line[[:space:]]+0:.*"gpioset".*output.*active-high.*\[used\]'; do
            attempts=$((attempts + 1))
            [ "$attempts" -lt 20 ] || fail 'selector was not acquired'
            sleep 0.1
        done
        # Check the PMIC driver readback as well as line ownership.
        state=$(awk '
            /parent:.*pmic@2:gpio@c000/ { selected=1; next }
            /^gpiochip/ { selected=0 }
            selected && /^[[:space:]]*gpio1[[:space:]]*:/ { print; exit }
        ' /sys/kernel/debug/gpio)
        echo "$state" | grep -Eq 'gpio1[[:space:]]*:[[:space:]]*out[[:space:]]+high' ||
            fail 'selector is not high in PMIC readback'
        attempts=0
        while ! amixer -c L2021 info >/dev/null 2>&1; do
            attempts=$((attempts + 1))
            [ "$attempts" -lt 40 ] || fail 'ALSA card L2021 unavailable'
            sleep 0.5
        done
        # Linux #522 fixes this backend at 2 channels and mask 0x3.
        # Feed DEC0 and DEC1 from the working DMIC2 input to match that mask.
        set_control 'MultiMedia2 Mixer VA_CODEC_DMA_TX_0' off off
        set_control 'MultiMedia3 Mixer VA_CODEC_DMA_TX_0' off off
        set_control 'MultiMedia3 Mixer PRI_MI2S_TX' off off
        for dec in 2 3 4 5 6 7; do
            set_control "TX_AIF1_CAP Mixer DEC$dec" off off
        done
        for dec in 0 1; do
            set_control "TX DMIC MUX$dec" DMIC2 3
            set_control "TX DEC$dec MUX" MSM_DMIC 0
            # Control value 84 is 0 dB; 96 adds 12 dB for speech capture.
            set_control "TX_DEC$dec Volume" 96 96
            set_control "TX_AIF1_CAP Mixer DEC$dec" on on
        done
        set_control 'MultiMedia3 Mixer TX_CODEC_DMA_TX_3' on on
        echo 'J716F microphone: selector and capture controls verified'
        ;;
    *) fail 'usage: j716f-microphone-setup {selector|routes}' ;;
esac
